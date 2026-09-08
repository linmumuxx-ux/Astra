#!/usr/bin/env python3
"""Opt-in: exercise Astra HTTP, MCP stdio and the configured live llm_wiki.

Run with backend/.venv/bin/python scripts/e2e_library.py. Uses an isolated Astra
DB, writes one uniquely named source to the configured project, and archives it
on exit. It never stops llm_wiki or modifies its configuration/source code.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


async def exercise(client, environment):
    from app.config.settings import get_settings
    from app.llm_wiki import LlmWikiClient
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    settings = get_settings()
    wiki = LlmWikiClient(settings)
    await wiki.verify_project()
    marker = "ASTRAE2E" + uuid4().hex[:10].upper()
    source_id = None
    report = {"marker": marker, "checks": {}}

    def api(method, path, **kwargs):
        response = client.request(method, "/api/library" + path, **kwargs)
        response.raise_for_status()
        return response.json()

    async def sync():
        result = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-c",
                "from app.runtime.celery_app import library_sync; print(library_sync())",
            ],
            cwd=BACKEND,
            env=environment,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError("Celery 同步入口执行失败：" + result.stderr[-2000:])
        status = api("GET", "/service/status")
        if status["failed_count"] or status["pending_count"]:
            raise RuntimeError(status["message"])

    async with (
        stdio_client(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "app.mcp_server"],
                cwd=str(BACKEND),
                env=environment,
            )
        ) as streams,
        ClientSession(*streams) as mcp,
    ):
        await mcp.initialize()

        async def tool(name, **arguments):
            result = await mcp.call_tool(name, arguments)
            if result.is_error:
                raise RuntimeError(str(result.content))
            data = result.structured_content
            if isinstance(data, dict) and set(data) == {"result"}:
                return data["result"]
            return data

        async def wait_content(expected):
            deadline = time.monotonic() + float(
                os.environ.get("ASTRA_LIBRARY_E2E_WAIT", "300")
            )
            last_progress = 0
            while time.monotonic() < deadline:
                hits = await tool("library_search", query=marker, limit=10)
                for hit in hits:
                    resource = await tool("library_get", resource_id=hit["resource_id"])
                    if expected in resource["content_md"]:
                        return resource
                if time.monotonic() - last_progress > 30:
                    print(f"Waiting for llm_wiki processing: {expected}", flush=True)
                    last_progress = time.monotonic()
                await asyncio.sleep(3)
            raise TimeoutError(f"llm_wiki 未在等待时间内生成可检索内容：{expected}")

        try:
            tools = {
                entry.name: entry.input_schema
                for entry in (await mcp.list_tools()).tools
            }
            assert tools["library_search"]["required"] == ["query"]
            assert tools["library_get"]["required"] == ["resource_id"]
            report["checks"]["mcp_schema"] = "passed"
            space = api("POST", "/spaces", json={"name": marker})
            candidate = await tool(
                "library_submit_experience",
                title=f"{marker} 流水线环境初始化超时",
                summary=f"{marker} 验证记录",
                content_md=(
                    f"# {marker} 流水线环境初始化超时\n\n"
                    f"仅用于 Astra 知识服务接入测试。故障标识是 {marker}。\n"
                    "现象：流水线环境初始化等待超过三十秒。\n"
                    "处理：将初始化超时调整为一百二十秒，然后重新初始化环境。\n"
                    "验证口令 INITIALCHECK：初始化日志出现 ready。"
                ),
            )
            source_id = candidate["id"]
            source = (
                settings.absolute_path(settings.llm_wiki_project_path)
                / "raw/sources/astra"
                / (source_id + ".md")
            )
            assert candidate["status"] == "candidate" and not source.exists()
            report["checks"]["candidate_not_exported"] = "passed"
            api(
                "POST",
                f"/knowledge/{source_id}/publish",
                json={"space_id": space["id"]},
            )
            await sync()
            assert source.exists()
            report["checks"]["publish_source_rescan"] = "passed"
            print("Published source; waiting for original llm_wiki ingest", flush=True)
            resource = await wait_content("INITIALCHECK")
            report["resource_id"] = resource["resource_id"]
            report["checks"]["mcp_search_get"] = "passed"
            feedback = await tool(
                "library_feedback",
                resource_id=resource["resource_id"],
                feedback_type="helpful",
                comment=marker,
            )
            assert feedback["resource_id"] == resource["resource_id"]
            summary = api("GET", "/usage/summary")
            assert summary["total_references"] > 0 and summary["feedback_count"] == 1
            report["checks"]["feedback_read_statistics"] = "passed"
            api(
                "PUT",
                f"/knowledge/{source_id}",
                json={
                    "content_md": (
                        f"# {marker} 流水线环境初始化超时\n\n"
                        f"故障标识 {marker}，更新后的处理步骤：将初始化超时调整为一百八十秒。\n"
                        "验证口令 UPDATEDCHECK：日志出现 environment_ready_v2 后再执行流水线。"
                    )
                },
            )
            await sync()
            assert "UPDATEDCHECK" in source.read_text()
            await wait_content("UPDATEDCHECK")
            report["checks"]["published_update_search"] = "passed"
            raw = await wiki.request(
                "POST",
                wiki.project_route + "/search",
                json={
                    "query": "流水线环境初始化超时",
                    "topK": 10,
                    "includeContent": False,
                },
            )
            report["search_mode"] = raw.get("mode")
            report["vector_hits"] = raw.get("vectorHits")
            api("POST", f"/knowledge/{source_id}/archive")
            await sync()
            assert not source.exists()
            report["checks"]["archive_source_rescan"] = "passed"
            # Observe cleanup without treating accepted upstream limitations as success.
            await asyncio.sleep(5)
            hits = await tool("library_search", query=marker)
            report["archive_remaining_hits"] = len(hits)
            report["known_limitation"] = (
                "共享 Wiki 页面可能保留已归档来源的正文；rescan 不代表加工完成"
            )
            return report
        finally:
            if source_id:
                detail = api("GET", f"/knowledge/{source_id}")
                if detail["status"] == "published":
                    api("POST", f"/knowledge/{source_id}/archive")
                await sync()


async def verify_unavailable(environment):
    """Exercise a real refused connection without stopping the user's llm_wiki."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        offline_env = {
            **environment,
            "ASTRA_LLM_WIKI_API_BASE_URL": f"http://127.0.0.1:{port}/api/v1",
        }
        async with (
            stdio_client(
                StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "app.mcp_server"],
                    cwd=str(BACKEND),
                    env=offline_env,
                )
            ) as streams,
            ClientSession(*streams) as mcp,
        ):
            await mcp.initialize()
            result = await mcp.call_tool(
                "library_search", {"query": "流水线环境初始化超时"}
            )
            assert result.is_error
            assert any(
                "知识服务暂不可用" in getattr(content, "text", "")
                for content in result.content
            )


def main():
    with tempfile.TemporaryDirectory(prefix="astra-library-e2e-") as temp:
        os.environ["ASTRA_DATABASE_URL"] = f"sqlite+aiosqlite:///{temp}/astra.db"
        os.environ["ASTRA_SEED_DEMO"] = "false"
        os.environ["ASTRA_ASSISTANT_ENABLED"] = "false"
        os.environ["ASTRA_LLM_WIKI_ENABLED"] = "true"
        os.environ["ASTRA_MCP_TRANSPORT"] = "stdio"
        os.environ["ASTRA_RUNTIME_DIR"] = f"{temp}/run"
        environment = dict(os.environ)
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env=environment,
            check=True,
            capture_output=True,
        )
        from app.main import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            report = asyncio.run(exercise(client, environment))
        asyncio.run(verify_unavailable(environment))
        report["checks"]["service_unavailable_no_fallback"] = "passed"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        output = ROOT / ".astra" / "library-e2e-result.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
