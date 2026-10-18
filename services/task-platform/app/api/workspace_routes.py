"""A task-bound native protocol gateway, not a second OpenCode API or UI implementation."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.routes import require_task
from app.config.settings import REPO_ROOT
from app.database import get_session
from app.domain import ExecutionMode, TaskStatus
from app.executors.errors import OpenCodeSessionNotFound
from app.models import RuntimeSession
from app.runtime.lifecycle import RuntimeService, RuntimeStateError
from app.runtime.session_connection import connect, resolve_environment, session_tree
from app.runtime.workspace_changes import collect_workspace_changes, workspace_diff
from app.runtime.workspace_files import (
    MAX_UPLOAD,
    check_request_path,
    same_workspace_path,
    upload,
    validate_path,
)
from app.schemas import ExecutionStopConfirm, RetrySubmission, TaskRead

router = APIRouter(prefix="/api/tasks/{task_id}")


class _Upstream:
    def __init__(self, status_code: int, content: bytes, headers: dict[str, str]) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def json(self):
        return json.loads(self.content) if self.content else None
# Task Workspace capability model: a task-bound, read-only window onto the
# employee's OpenCode server plus the native conversation/reply writes below.
# GET-only paths must be non-mutating and must not create PTYs, processes or
# sessions; anything capable of executing work is denied here and only reachable
# through an explicit task action. `/pty/shells` only lists shells for the native
# Settings page, so it stays read-only while `/pty` (PTY lifecycle) is faked empty.
READ_PATHS = {
    # Server / workspace observation
    "/global/health",
    "/project",
    "/project/current",
    "/path",
    "/vcs",
    "/vcs/diff",
    "/vcs/diff/raw",
    "/file",
    "/file/content",
    "/file/status",
    "/find",
    "/find/file",
    "/find/symbol",
    "/lsp",
    "/formatter",
    "/experimental/resource",
    "/experimental/worktree",
    # Native Settings (read-only)
    "/global/config",
    "/config",
    "/config/providers",
    "/provider",
    "/provider/auth",
    "/agent",
    "/command",
    "/skill",
    "/mcp",
    "/api/reference",
    "/pty/shells",
    # Conversation observation
    "/session",
    "/session/status",
    "/permission",
    "/question",
    "/pty",
}
SESSION_READ = re.compile(r"^/session/([^/]+)(/(children|todo|diff|message)(/[^/]+)?)?$")
# OpenCode 1.18 的 v2 客户端用绝对路径 /api/...。只放行观察类 GET。
API_READ = re.compile(
    r"^/api/(?:health|provider|model|config|project|path|agent|command|skill|mcp|location|"
    r"global|file|find|vcs|lsp|formatter|experimental|permission|question|pty|session)(?:/.*)?$"
)
API_SESSION = re.compile(r"^/api/session/([^/]+)(/.*)?$")
API_SESSION_COLLECTIONS = {"active", "status"}
SESSION_WRITE = re.compile(
    r"^/session/([^/]+)/(prompt_async|message|abort|revert|unrevert|summarize|command)$"
)
REPLY = re.compile(r"^/(question|permission)/([^/]+)/(reply|reject)$")
# 原生 Workspace UI 直接按 Session 回答权限请求，与 /permission/{id}/reply 等价。
PERMISSION_REPLY = re.compile(r"^/session/([^/]+)/permissions/([^/]+)$")
OPENCODE_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
RETIRED_WORKSPACE_UI = "版本未知/界面已退役"
_SECRET_SEGMENTS = frozenset({"provider", "model", "config"})
_SECRET_CONTAINERS = frozenset({"settings", "options", "headers"})
_SECRET_FIELDS = frozenset(
    {"apikey", "api_key", "api-key", "x-api-key", "key", "token", "authorization", "password", "secret"}
)


def normalize_proxy_path(path: str) -> str:
    """Collapse duplicate and trailing slashes before allowlist and filter checks."""

    return "/" + "/".join(part for part in path.split("/") if part)


def carries_provider_secrets(path: str) -> bool:
    return bool(_SECRET_SEGMENTS.intersection(normalize_proxy_path(path).split("/")))


def redact_secret_fields(value: Any) -> Any:
    """Drop secret fields nested under settings, options, and headers."""

    if isinstance(value, list):
        for item in value:
            redact_secret_fields(item)
        return value
    if not isinstance(value, dict):
        return value
    for key, item in list(value.items()):
        if key.lower() in _SECRET_CONTAINERS:
            if isinstance(item, dict):
                for secret in [name for name in item if name.lower() in _SECRET_FIELDS]:
                    item.pop(secret, None)
            redact_secret_fields(item)
            continue
        redact_secret_fields(item)
    return value


def _api_route_missing(status: int, headers: dict[str, str]) -> bool:
    """v1 OpenCode serves its SPA document for an unknown /api path."""

    if status == 404:
        return True
    media = str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    return status == 200 and media == "text/html"


def _scope_session_list(data, allowed: set[str]):
    """v1 is an array. v2 is {data, cursor}; keep the envelope and filter data."""

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and item.get("id") in allowed]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        visible = [item for item in data["data"] if isinstance(item, dict) and item.get("id") in allowed]
        return {**data, "data": visible}
    return data


def _scope_session_active(data, allowed: set[str]):
    """v2 wraps the status map in data. A bare map is filtered the same way."""

    if not isinstance(data, dict):
        return data
    if isinstance(data.get("data"), dict):
        return {**data, "data": {key: value for key, value in data["data"].items() if key in allowed}}
    return {key: value for key, value in data.items() if key in allowed}


def workspace_ui_bundle(version: str) -> Path:
    return REPO_ROOT / "web" / "nexus" / "public" / "opencode-workspace" / version / "index.html"


_present_bundles: set[str] = set()


def bundle_installed(version: str) -> bool:
    """已安装的版本包不变，命中后不再查磁盘。缺失不缓存，装上后下一次就能看见。"""

    if version in _present_bundles:
        return True
    if workspace_ui_bundle(version).is_file():
        _present_bundles.add(version)
        return True
    return False


def workspace_ui_for(snapshot: dict | None) -> tuple[str, str | None, str | None]:
    """Select the UI for the version already stored on the session.

    Missing or unreadable versions stay unknown. A recorded version is never
    replaced with the current release; a retired bundle is reported as such.
    """
    raw = (snapshot or {}).get("opencode_version")
    if raw is None or not str(raw).strip():
        return "unknown", None, RETIRED_WORKSPACE_UI
    version = str(raw).strip().removeprefix("v")
    if not OPENCODE_VERSION.fullmatch(version):
        return version or "unknown", None, RETIRED_WORKSPACE_UI
    if not bundle_installed(version):
        return version, None, f"{RETIRED_WORKSPACE_UI}（{version}）"
    return version, f"/opencode-workspace/{version}/index.html", None


async def runtime_worker_online(session, snapshot: dict | None) -> bool | None:
    """Worker 通道上的在线事实。非 Worker 通道不在这里判断。"""

    if not isinstance(snapshot, dict):
        return None
    environment_id = snapshot.get("environment_id")
    if environment_id is None:
        return None
    from app.models import OpenCodeExecutionEnvironment, WorkerInstance

    stored = await session.get(OpenCodeExecutionEnvironment, environment_id)
    if stored is None or stored.worker_channel != "worker":
        return None
    instance = await session.scalar(
        select(WorkerInstance).where(WorkerInstance.environment_id == stored.id)
    )
    return bool(instance is not None and instance.status == "online")


def error_response(exc):
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, OpenCodeSessionNotFound):
        return HTTPException(404, "Session 不存在；请显式选择恢复或新建 Session")
    if isinstance(exc, PermissionError):
        return HTTPException(403, str(exc))
    if isinstance(exc, (ValueError, RuntimeStateError)):
        return HTTPException(409, str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(409, f"Workspace 不存在：{exc}")
    return HTTPException(503, f"当前 OpenCode Runtime 不可连接：{exc}")


@router.post("/start", response_model=TaskRead)
async def start_task(task_id: str, session=Depends(get_session)):
    await require_task(task_id, session)
    try:
        return await RuntimeService(session).start(task_id)
    except Exception as exc:
        raise error_response(exc) from exc


@router.post("/restart", response_model=TaskRead)
async def restart_task(task_id: str, session=Depends(get_session)):
    await require_task(task_id, session)
    try:
        return await RuntimeService(session).start(task_id, restart=True)
    except Exception as exc:
        raise error_response(exc) from exc


@router.post("/pause", response_model=TaskRead)
async def pause_task(task_id: str, session=Depends(get_session)):
    task = await require_task(task_id, session)
    if task.status != TaskStatus.RUNNING.value:
        raise HTTPException(409, "只有执行中的任务可以暂停")
    try:
        return await RuntimeService(session).stop(task_id, cancel_task=False)
    except Exception as exc:
        raise error_response(exc) from exc


@router.post("/resume", response_model=TaskRead)
async def resume_task(task_id: str, session=Depends(get_session)):
    task = await require_task(task_id, session)
    if task.status != TaskStatus.WAITING.value:
        raise HTTPException(409, "只有等待中的任务可以恢复")
    try:
        if task.current_session_id:
            return await RuntimeService(session).continue_task(task_id)
        return await RuntimeService(session).start(task_id)
    except Exception as exc:
        raise error_response(exc) from exc


@router.post("/stop", response_model=TaskRead)
async def stop_task(task_id: str, session=Depends(get_session)):
    await require_task(task_id, session)
    try:
        return await RuntimeService(session).stop(task_id)
    except Exception as exc:
        raise error_response(exc) from exc


@router.post("/confirm-execution-stop", response_model=TaskRead)
async def confirm_execution_stop(
    task_id: str,
    body: ExecutionStopConfirm,
    session=Depends(get_session),
    user_id: Annotated[str, Header(alias="X-Astra-User-Id")] = "",
):
    await require_task(task_id, session)
    try:
        return await RuntimeService(session).confirm_execution_stop(
            task_id, operator=user_id, reason=body.reason
        )
    except Exception as exc:
        raise error_response(exc) from exc


@router.post("/reconnect", response_model=TaskRead)
async def reconnect_task(task_id: str, session=Depends(get_session)):
    await require_task(task_id, session)
    try:
        return await RuntimeService(session).refresh(task_id)
    except OpenCodeSessionNotFound as exc:
        # refresh() already records SESSION_MISSING; do not overwrite it with a
        # transport-unknown marker.
        raise error_response(exc) from exc
    except Exception as exc:
        await session.rollback()
        await RuntimeService(session).disconnected(task_id, exc)
        raise error_response(exc) from exc


@router.get("/workspace")
async def task_workspace(task_id: str, session_id: str | None = None, session=Depends(get_session)):
    task = await require_task(task_id, session)
    bindings = (
        await session.scalars(
            select(RuntimeSession)
            .where(
                RuntimeSession.task_id == task.id,
            )
            .order_by(RuntimeSession.created_at.desc())
        )
    ).all()
    selected = next((item for item in bindings if item.id == (session_id or task.current_session_id)), None)
    if session_id and not selected:
        raise HTTPException(404, "Session 不属于此任务")

    selected_snapshot = selected.environment if selected else task.execution_environment_snapshot
    selected_version, selected_ui, selected_ui_error = workspace_ui_for(selected_snapshot)
    worker_online = await runtime_worker_online(session, selected_snapshot)

    def session_item(item: RuntimeSession):
        version, workspace_ui, workspace_ui_error = workspace_ui_for(item.environment)
        return {
            "id": item.id,
            "workspace": item.workspace,
            "created_at": item.created_at,
            "status": item.status,
            "superseded_by": item.superseded_by,
            "finished_at": item.finished_at,
            "current": item.id == task.current_session_id,
            "opencode_version": version,
            "workspace_ui": workspace_ui,
            "workspace_ui_error": workspace_ui_error,
        }

    return {
        "task_id": task.id,
        "task_status": task.status,
        "runtime": {
            "server": f"/api/tasks/{task.id}/opencode",
            "session_id": selected.id if selected else None,
            "workspace": selected.workspace if selected else task.workspace,
            "connection": task.runtime_connection,
            "error": task.runtime_error,
            "opencode_version": selected_version,
            "workspace_ui": selected_ui,
            "workspace_ui_error": selected_ui_error,
            "worker_online": worker_online,
        },
        "sessions": [session_item(item) for item in bindings],
    }


@router.post("/files/{filename}")
async def upload_file(task_id: str, filename: str, request: Request, session=Depends(get_session)):
    task = await require_task(task_id, session)
    if not task.workspace:
        raise HTTPException(409, "任务尚未准备 Workspace")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_UPLOAD:
            raise HTTPException(413, "文件不能超过 20 MB")
    try:
        environment = await resolve_environment(session, task)
        await session.commit()
        path = await upload(environment, task.workspace, filename, bytes(content))
    except Exception as exc:
        raise error_response(exc) from exc
    return {"path": path}


def event_session(event):
    props = event.get("properties", {})
    info = props.get("info", {})
    return (
        props.get("sessionID")
        or props.get("part", {}).get("sessionID")
        or info.get("sessionID")
        or (info.get("id") if event.get("type", "").startswith("session.") else None)
    )


async def native_events(environment, workspace, root, global_stream):
    async with connect(environment, start=True) as client:
        allowed = await session_tree(client, Path(workspace), root)
        if getattr(client, "records_fetch", False):
            stream = client.events(Path(workspace), consumer=f"browser:{uuid4().hex}")
        else:
            stream = client.events(Path(workspace))
        async for event in stream:
            props = event.get("properties", {})
            info = props.get("info", {})
            if event.get("type") == "session.created" and info.get("parentID") in allowed:
                allowed.add(info["id"])
            if event.get("type") == "astra.keepalive":
                yield ": keepalive\n\n"
                continue
            if event.get("type") == "astra.event_gap":
                value = {"directory": workspace, "payload": event} if global_stream else event
                yield f"data: {json.dumps(value, ensure_ascii=False)}\n\n"
                continue
            sid = event_session(event)
            if sid and sid not in allowed:
                continue
            if not sid and event.get("type") not in {
                "server.connected",
                "server.heartbeat",
                "file.edited",
                "file.watcher.updated",
                "vcs.branch.updated",
                "lsp.updated",
                "instance.disposed",
            }:
                continue
            value = {"directory": workspace, "payload": event} if global_stream else event
            yield f"data: {json.dumps(value, ensure_ascii=False)}\n\n"


async def persist_attachments(body, environment, workspace):
    for part in body.get("parts", []):
        if part.get("type") != "file":
            continue
        url = part.get("url", "")
        if url.startswith("data:"):
            header, encoded = url.split(",", 1)
            if ";base64" not in header or len(encoded) > MAX_UPLOAD * 4 // 3 + 8:
                raise ValueError("附件格式或大小无效")
            path = await upload(
                environment,
                workspace,
                part.get("filename") or "attachment",
                base64.b64decode(encoded, validate=True),
            )
            part["url"] = (
                Path(path).as_uri()
                if environment.mode == ExecutionMode.LOCAL
                else PurePosixPath(path).as_uri()
            )
        elif url.startswith("file:"):
            parsed = urlparse(url)
            if parsed.netloc:
                raise PermissionError("不允许外部文件地址")
            value = unquote(parsed.path)
            if environment.mode == ExecutionMode.LOCAL:
                value = url2pathname(value)
            await validate_path(environment, workspace, value)
        else:
            raise PermissionError("附件必须写入任务 Workspace")
    return body


@router.api_route("/opencode/{session_id}/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"])
async def native_proxy(
    task_id: str, session_id: str, path: str, request: Request, session=Depends(get_session)
):
    task = await require_task(task_id, session)
    binding = await session.get(RuntimeSession, session_id)
    if not binding or binding.task_id != task.id:
        raise HTTPException(404, "Session 不属于此任务")
    # Environment and directory are bound in the DB, never selected by browser-supplied paths.
    from app.models import OpenCodeExecutionEnvironment
    from app.runtime.environment import environment_from_snapshot

    environment = environment_from_snapshot(binding.environment, binding.employee_id)
    stored = await session.get(OpenCodeExecutionEnvironment, binding.environment["environment_id"])
    if stored:
        environment.ssh_password = stored.ssh_password
        environment.worker_channel = stored.worker_channel
    workspace = binding.workspace
    # Release the read transaction before path validation, SSH/OpenCode startup,
    # SSE or upstream HTTP. Native Workspace requests can be long-lived.
    await session.commit()
    if "workspace" in request.query_params or "x-opencode-workspace" in request.headers:
        raise HTTPException(403, "不允许覆盖任务绑定")
    for key, value in request.query_params.multi_items():
        if key.startswith("location") and (
            key != "location[directory]"
            or not same_workspace_path(environment, workspace, unquote(value))
        ):
            raise HTTPException(403, "不允许覆盖任务绑定")
    requested = request.query_params.get("directory") or request.headers.get("x-opencode-directory")
    requested_path = unquote(requested) if requested else None
    native_path = normalize_proxy_path(path)
    directory = workspace
    if requested_path and not same_workspace_path(environment, workspace, requested_path):
        if request.method != "GET" or native_path not in {"/vcs/diff", "/vcs/diff/raw"}:
            raise HTTPException(403, "Workspace 不属于此任务")
        try:
            await validate_path(environment, workspace, requested_path)
        except Exception as exc:
            raise error_response(exc) from exc
        directory = requested_path
    method = request.method
    if method == "GET" and native_path in {"/vcs/diff", "/vcs/diff/raw"}:
        try:
            # `git` is the native uncommitted view; the explicit task view also
            # includes commits since this workspace's first Session baseline.
            mode = request.query_params.get("mode", "task")
            if mode not in {"git", "task"}:
                raise ValueError("不支持的 Diff 模式")
            diffs = await workspace_diff(
                session, task, cumulative=mode == "task", directory=directory,
                environment=environment, workspace=workspace,
            )
            if native_path.endswith("/raw"):
                return Response("".join(item["patch"] for item in diffs), media_type="text/x-diff")
            return diffs
        except Exception as exc:
            raise error_response(exc) from exc
    match = SESSION_READ.fullmatch(native_path) if method == "GET" else SESSION_WRITE.fullmatch(native_path)
    reply = REPLY.fullmatch(native_path) if method == "POST" else None
    permission_reply = PERMISSION_REPLY.fullmatch(native_path) if method == "POST" else None
    if permission_reply and permission_reply[1] != session_id:
        raise HTTPException(403, "历史 Session 只读")
    pending = (reply[1], reply[2]) if reply else (
        ("permission", permission_reply[2]) if permission_reply else None
    )
    if method != "GET" and task.status in {"SUCCEEDED", "CANCELED"}:
        raise HTTPException(409, "任务已结束；请显式重新开始")
    if method != "GET" and session_id != task.current_session_id:
        raise HTTPException(403, "历史 Session 只读")
    if method == "GET" and native_path in {"/global/event", "/event"}:
        await session.commit()
        return StreamingResponse(
            native_events(environment, workspace, session_id, native_path == "/global/event"),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    api_read = method == "GET" and API_READ.fullmatch(native_path) is not None
    if not match and not pending and not (method == "GET" and native_path in READ_PATHS) and not api_read:
        raise HTTPException(403, "此接口不属于 Task Workspace 的权限范围")
    try:
        await check_request_path(
            environment, workspace, request.query_params.get("path", "."), native_path=native_path
        )
        async with connect(environment, start=True) as client:
            allowed = await session_tree(client, Path(workspace), session_id)
            # Global reads such as /session/status are not per-session resources;
            # their payloads are filtered to `allowed` below instead of rejected here.
            if match and native_path not in READ_PATHS and match[1] not in allowed:
                raise PermissionError("Session 不属于此任务")
            api_session = API_SESSION.fullmatch(native_path)
            if (
                api_session
                and api_session[1] not in API_SESSION_COLLECTIONS
                and api_session[1] not in allowed
            ):
                raise PermissionError("Session 不属于此任务")
            if method != "GET" and match and match[1] != session_id:
                raise PermissionError("子 Session 只读")
            body = json.loads(await request.body() or b"{}") if method != "GET" else None
            if body and {"directory", "sessionID", "workspace", "location"}.intersection(body):
                raise PermissionError("不允许覆盖任务绑定")
            if pending:
                items = await client.request(
                    "GET",
                    f"/{pending[0]}",
                    directory=Path(workspace),
                    session_id=session_id,
                    task_id=task.id,
                )
                if not any(item["id"] == pending[1] and item.get("sessionID") in allowed for item in items):
                    raise PermissionError("请求不属于此任务 Session")
            if native_path.endswith(("/prompt_async", "/message", "/command")) and method == "POST":
                await persist_attachments(body, environment, workspace)
                await RuntimeService(session).send(
                    task.id,
                    body,
                    expected_session_id=session_id,
                    native_action="command" if native_path.endswith("/command") else "prompt_async",
                )
                return Response(status_code=204)
            if native_path.endswith("/abort") and method == "POST":
                await RuntimeService(session).stop(task.id, cancel_task=False)
                return True
            if native_path == "/pty":
                return []  # Arbitrary terminals are outside the task-scoped API boundary.
            params = dict(request.query_params)
            params["directory"] = directory
            # v2 resolves /api/model and friends from location[directory]. Always pin it
            # to this task; a missing value follows OpenCode's last directory.
            if native_path.startswith("/api/") or "location[directory]" in params:
                params["location[directory]"] = workspace
            for key in ("sessionID", "sessionId", "session_id"):
                if key in params and params[key] not in allowed:
                    raise PermissionError("Session 不属于此任务")
            forward_path = "/project/current" if native_path == "/project" else native_path
            status, content, headers = await client.exchange(
                method,
                forward_path,
                params=params,
                body=body,
                session_id=session_id,
                task_id=task.id,
            )
            if forward_path.startswith("/api/") and _api_route_missing(status, headers):
                # v1 OpenCode answers an unknown /api path with the SPA document (200
                # text/html) or 404. Retry the unprefixed route once.
                alternate = forward_path.removeprefix("/api") or "/"
                status, content, headers = await client.exchange(
                    method,
                    alternate,
                    params=params,
                    body=body,
                    session_id=session_id,
                    task_id=task.id,
                )
            upstream = _Upstream(status, content, headers)
            if upstream.is_error:
                return Response(
                    content=upstream.content,
                    status_code=upstream.status_code,
                    media_type=upstream.headers.get("content-type", "application/json"),
                )
            if native_path == "/vcs/diff/raw":
                return Response(content=upstream.content, media_type="text/x-diff")
            data = upstream.json() if upstream.content else None
            if carries_provider_secrets(native_path):
                redact_secret_fields(data)
            shape = native_path.removeprefix("/api") if native_path.startswith("/api/") else native_path
            if shape == "/session":
                data = _scope_session_list(data, allowed)
            elif shape == "/session/active":
                data = _scope_session_active(data, allowed)
            elif shape == "/session/status":
                data = {key: value for key, value in data.items() if key in allowed}
            elif shape in {"/question", "/permission"}:
                data = [item for item in data if item.get("sessionID") in allowed]
            elif shape in {"/project", "/project/current"}:
                data = {**data, "worktree": workspace, "sandboxes": []}
                if shape == "/project":
                    data = [data]
            elif shape == "/path":
                data = {
                    **data,
                    "directory": workspace,
                    "worktree": workspace,
                    "home": workspace,
                    "config": workspace,
                    "state": workspace,
                }
            elif shape in {"/global/config", "/config"}:
                data = {
                    key: value
                    for key, value in data.items()
                    if key
                    in {
                        "snapshot",
                        "model",
                        "small_model",
                        "default_agent",
                        "username",
                        "enabled_providers",
                        "disabled_providers",
                    }
                }
                if environment.model_name:
                    data["model"] = environment.model_name
            elif shape in {"/provider", "/config/providers"} and isinstance(data, dict):
                for provider in data.get("all", data.get("providers", [])):
                    for key in ("key", "options", "headers"):
                        provider.pop(key, None)
                    for model in provider.get("models", {}).values():
                        model["options"] = {}
                        model["headers"] = {}
            elif shape == "/experimental/worktree":
                data = []
            if reply or method != "GET":
                await RuntimeService(session).refresh(task.id, client=client)
            return Response(
                content=json.dumps(data, ensure_ascii=False),
                media_type="application/json",
                headers={
                    key: value
                    for key, value in upstream.headers.items()
                    if key in {"link", "x-next-cursor", "x-has-more"}
                },
            )
    except Exception as exc:
        raise error_response(exc) from exc


@router.post("/retry-submission", response_model=TaskRead)
async def retry_submission(
    task_id: str,
    body: RetrySubmission | None = None,
    session=Depends(get_session),
):
    await require_task(task_id, session)
    try:
        return await RuntimeService(session).retry_submission(
            task_id, confirm_unknown=bool(body and body.confirm_unknown)
        )
    except Exception as exc:
        raise error_response(exc) from exc


@router.get("/repo")
async def task_repo(task_id: str, session=Depends(get_session)):
    import asyncio

    from app.domain import ExecutionMode

    task = await require_task(task_id, session)
    if not task.workspace:
        raise HTTPException(409, "Workspace 尚未准备")
    environment = await resolve_environment(session, task)
    await session.commit()
    try:
        await validate_path(environment, task.workspace, ".")
        from app.runtime.worker_files import WorkerFileError, environment_uses_worker, worker_git

        worker = await environment_uses_worker(environment)
        status_overflow = False

        async def git(*args):
            nonlocal status_overflow
            if worker:
                try:
                    code, output = await worker_git(environment, task.workspace, args)
                except WorkerFileError as exc:
                    if args[:1] == ("status",) and exc.code == "too_large":
                        status_overflow = True
                        return ""
                    raise
                return output.strip() if code == 0 else ""
            if environment.mode == ExecutionMode.LOCAL:
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "-C",
                    task.workspace,
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                output, _ = await proc.communicate()
                return output.decode().strip() if proc.returncode == 0 else ""
            raise RuntimeError("远程环境尚未安装 Worker")

        commit = await git("rev-parse", "HEAD")
        branch = await git("branch", "--show-current")
        changes = await git("status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all")
        origin = await git("config", "--get", "remote.origin.url")
        common_dir = await git("rev-parse", "--path-format=absolute", "--git-common-dir")
        name = (
            origin.rstrip("/").split("/")[-1].removesuffix(".git")
            if origin
            else Path(common_dir).parent.name if common_dir else Path(task.workspace).name
        )
        task_changes = await collect_workspace_changes(session, task)
        return {
            "name": name,
            "branch": branch,
            "commit": commit,
            "dirty": status_overflow or bool(changes),
            "changes": sum(bool(entry) for entry in changes.split("\0")),
            "task_changes": task_changes,
        }
    except Exception as exc:
        raise error_response(exc) from exc
