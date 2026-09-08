"""The original llm_wiki local HTTP API contract; no local retrieval engine."""

from pathlib import PurePosixPath
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config.settings import Settings, get_settings
from app.library_schemas import LibraryResource, LibrarySearchResult


class LlmWikiError(Exception):
    pass


def wiki_resource_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or len(value) > 512
        or "\\" in value
        or "\x00" in value
        or path.is_absolute()
        or ".." in path.parts
        or str(path) != value
        or len(path.parts) < 2
        or path.parts[0] != "wiki"
        or path.suffix != ".md"
    ):
        raise LlmWikiError("resource_id 必须是 wiki/ 下的 Markdown 相对路径")
    return value


class _SearchHit(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    path: str
    title: str
    snippet: str
    score: float


class _SearchResponse(BaseModel):
    results: list[_SearchHit]


class _FileResponse(BaseModel):
    model_config = ConfigDict(strict=True)
    path: str
    content: str


class LlmWikiClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    async def request(self, method: str, path: str, **kwargs) -> dict:
        settings = self.settings
        if not settings.llm_wiki_enabled:
            raise LlmWikiError("知识服务暂不可用：未启用 llm_wiki")
        if not settings.llm_wiki_project_id:
            raise LlmWikiError("知识服务暂不可用：未配置 project_id")
        headers = {"Accept": "application/json"}
        if settings.llm_wiki_api_token:
            headers["Authorization"] = f"Bearer {settings.llm_wiki_api_token}"
        try:
            async with httpx.AsyncClient(timeout=settings.llm_wiki_timeout, trust_env=False) as client:
                response = await client.request(
                    method, settings.llm_wiki_api_base_url + path, headers=headers, **kwargs
                )
        except httpx.TimeoutException:
            raise LlmWikiError("知识服务暂不可用：HTTP 请求超时") from None
        except httpx.RequestError:
            raise LlmWikiError("知识服务暂不可用：无法连接 llm_wiki") from None
        if response.status_code in {401, 403}:
            raise LlmWikiError("知识服务暂不可用：API Token 错误或权限不足")
        if response.status_code == 404:
            raise LlmWikiError("知识服务暂不可用：项目或资源不存在")
        if not response.is_success:
            raise LlmWikiError(f"知识服务暂不可用：HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise LlmWikiError("知识服务暂不可用：响应不是 JSON") from None
        if not isinstance(data, dict) or data.get("ok") is False:
            raise LlmWikiError("知识服务暂不可用：API 返回失败结果")
        return data

    @property
    def project_route(self) -> str:
        return f"/projects/{quote(self.settings.llm_wiki_project_id, safe='')}"

    async def verify_project(self) -> None:
        """Check the write target against the authenticated service before touching files."""
        from pathlib import Path

        data = await self.request("GET", "/projects")
        projects = data.get("projects")
        if not isinstance(projects, list):
            raise LlmWikiError("知识服务暂不可用：项目响应格式错误")
        project = next(
            (p for p in projects if isinstance(p, dict) and p.get("id") == self.settings.llm_wiki_project_id),
            None,
        )
        if project is None:
            raise LlmWikiError("知识服务暂不可用：project_id 不存在")
        configured_path = self.settings.llm_wiki_project_path
        if (
            configured_path is None
            or not isinstance(project.get("path"), str)
            or self.settings.absolute_path(configured_path) != Path(project["path"]).resolve()
        ):
            raise LlmWikiError("知识服务暂不可用：PROJECT_PATH 与 API 项目目录不一致")
        if not project.get("current"):
            raise LlmWikiError("知识服务暂不可用：请在 llm_wiki 桌面应用打开配置的项目")

    async def search(self, query: str, limit: int) -> list[LibrarySearchResult]:
        data = await self.request(
            "POST",
            self.project_route + "/search",
            json={
                "query": query,
                "topK": limit,
                "includeContent": False,
            },
        )
        try:
            hits = _SearchResponse.model_validate(data).results
        except ValidationError:
            raise LlmWikiError("知识服务暂不可用：搜索响应格式错误") from None
        return [
            LibrarySearchResult(
                resource_id=wiki_resource_path(hit.path),
                path=hit.path,
                title=hit.title,
                excerpt=hit.snippet,
                score=hit.score,
            )
            for hit in hits[:limit]
        ]

    async def read(self, resource_id: str) -> LibraryResource:
        path = wiki_resource_path(resource_id)
        data = await self.request("GET", self.project_route + "/files/content", params={"path": path})
        try:
            resource = _FileResponse.model_validate(data)
        except ValidationError:
            raise LlmWikiError("知识服务暂不可用：读取响应格式错误") from None
        if resource.path != path:
            raise LlmWikiError("知识服务暂不可用：返回资源路径不匹配")
        return LibraryResource(resource_id=path, path=path, content_md=resource.content)

    async def rescan(self) -> None:
        data = await self.request("POST", self.project_route + "/sources/rescan")
        if data.get("ok") is not True or not isinstance(data.get("result"), dict):
            raise LlmWikiError("知识服务暂不可用：rescan 响应格式错误")
        queue = data["result"].get("queue")
        if not isinstance(queue, dict) or not isinstance(queue.get("tasks"), list):
            raise LlmWikiError("知识服务暂不可用：rescan 队列响应格式错误")
        if any(not isinstance(task, dict) for task in queue["tasks"]):
            raise LlmWikiError("知识服务暂不可用：rescan 任务响应格式错误")
        if any(task.get("status") == "failed" for task in queue["tasks"]):
            raise LlmWikiError("知识服务暂不可用：源文件扫描任务失败")
