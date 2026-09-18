import asyncio
import os
import sqlite3
import subprocess
import sys
from functools import partial
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config.settings import Settings
from app.library_schemas import (
    KnowledgeCreate,
    KnowledgePatch,
    KnowledgePublishWrite,
    KnowledgeSpaceCreate,
    KnowledgeSpacePatch,
    LibraryFeedbackInput,
    LibrarySearchInput,
    LibrarySubmitExperienceInput,
)
from app.library_service import KnowledgeService, LibraryPrincipal
from app.library_sync import sync_pending, write_source
from app.llm_wiki import LlmWikiClient, LlmWikiError
from app.models import Base, KnowledgeFeedback, KnowledgeItem, KnowledgeSync, KnowledgeUsage


@pytest.fixture
async def wiki_env(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        llm_wiki_enabled=True,
        llm_wiki_project_id="project-1",
        llm_wiki_project_path=tmp_path / "project",
        llm_wiki_api_token="test-secret",
        runtime_dir=tmp_path / "run",
    )
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    state = {"status": 200, "calls": [], "pages": {}, "on_rescan": None}
    directory = settings.llm_wiki_project_path / "raw/sources/astra"

    async def respond(request):
        state["calls"].append(request)
        assert request.headers["Authorization"] == "Bearer test-secret"
        if isinstance(state["status"], Exception):
            raise state["status"]
        if state["status"] != 200:
            return httpx.Response(state["status"], json={"ok": False, "error": "test-secret"})
        path = request.url.path
        if path.endswith("/projects"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "projects": [
                        {
                            "id": "project-1",
                            "path": str(settings.llm_wiki_project_path),
                            "current": True,
                        }
                    ],
                },
            )
        if path.endswith("/sources/rescan"):
            state["pages"] = {f"wiki/sources/{p.name}": p.read_text() for p in directory.glob("*.md")}
            if state["on_rescan"]:
                await state["on_rescan"]()
            return httpx.Response(200, json={"ok": True, "result": {"queue": {"tasks": []}}})
        if path.endswith("/search"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "results": [
                        {"path": path, "title": "知识", "snippet": content[-100:], "score": 1.25}
                        for path, content in state["pages"].items()
                    ],
                },
            )
        if path.endswith("/files/content"):
            resource = request.url.params["path"]
            if resource not in state["pages"]:
                return httpx.Response(404)
            return httpx.Response(200, json={"path": resource, "content": state["pages"][resource]})
        raise AssertionError(path)

    monkeypatch.setattr(
        httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(respond))
    )
    monkeypatch.setattr("app.llm_wiki.get_settings", lambda: settings)
    monkeypatch.setattr("app.library_service.get_settings", lambda: settings)
    async with sessions() as session:
        service = KnowledgeService(session)
        space = await service.create_space(KnowledgeSpaceCreate(name="Public"), LibraryPrincipal())
    yield settings, sessions, state, space.id, directory
    await engine.dispose()


async def publish(sessions, space_id, title="timeout"):
    async with sessions() as session:
        service = KnowledgeService(session)
        item = await service.create_knowledge(
            KnowledgeCreate(space_id=space_id, title=title, content_md="original body"), LibraryPrincipal()
        )
        await service.publish(item.id, KnowledgePublishWrite(space_id=space_id), LibraryPrincipal())
        return item.id


async def test_lifecycle_and_resource_usage_without_runtime_identity(wiki_env):
    settings, sessions, state, space_id, directory = wiki_env
    async with sessions() as session:
        service = KnowledgeService(session)
        candidate = await service.mcp_submit_experience(
            LibrarySubmitExperienceInput(title="流水线环境初始化超时", content_md="检查初始化日志")
        )
        assert candidate.status == "candidate" and candidate.type == "experience"
        assert await session.get(KnowledgeSync, candidate.id) is None
        assert await sync_pending(session, settings) == 0
        assert not directory.exists()
        await service.publish(candidate.id, KnowledgePublishWrite(space_id=space_id), LibraryPrincipal())
        assert await sync_pending(session, settings) == 1
        source = directory / f"{candidate.id}.md"
        assert "astra_knowledge_id:" in source.read_text()
        hits = await service.mcp_search(LibrarySearchInput(query="流水线环境初始化超时"))
        resource = await service.mcp_get(hits[0].resource_id)
        assert "检查初始化日志" in resource.content_md
        feedback = await service.mcp_feedback(
            LibraryFeedbackInput(resource_id=resource.resource_id, feedback_type="helpful")
        )
        assert feedback.resource_id == resource.resource_id
        events = (
            await session.scalars(
                select(KnowledgeUsage).where(KnowledgeUsage.resource_id == resource.resource_id)
            )
        ).all()
        assert [event.action for event in events] == ["search_hit", "read", "feedback"]
        assert all(
            event.employee_id is None and event.task_id is None and event.run_id is None for event in events
        )
        summary = await service.usage_summary()
        assert summary.total_references == 1 and summary.used_resources == 1
        assert summary.feedback_count == 1
        assert summary.top_knowledge[0].resource_id == resource.resource_id
        recent = await service.recent_usage()
        assert recent[0].resource_id == resource.resource_id
        await service.update_knowledge(
            candidate.id, KnowledgePatch(content_md="更新后的步骤"), LibraryPrincipal()
        )
        await sync_pending(session, settings)
        assert "更新后的步骤" in (await service.mcp_get(resource.resource_id)).content_md
        await service.archive(candidate.id, LibraryPrincipal())
        await sync_pending(session, settings)
        assert not source.exists()
        assert await service.mcp_search(LibrarySearchInput(query="初始化")) == []
        with pytest.raises(LlmWikiError, match="不存在"):
            await service.mcp_get(resource.resource_id)
        await service.delete_knowledge(candidate.id, LibraryPrincipal())
        assert await session.get(KnowledgeSync, candidate.id) is not None
        assert await session.scalar(select(func.count(KnowledgeFeedback.id))) == 1
        assert (await service.mcp_related(resource.resource_id))["status"] == "unsupported"


@pytest.mark.parametrize(
    "status, message",
    [
        (401, "Token"),
        (404, "不存在"),
        (500, "HTTP 500"),
        (httpx.ReadTimeout("test-secret"), "超时"),
        (httpx.ConnectError("test-secret"), "无法连接"),
    ],
)
async def test_unavailable_persists_failure_without_rolling_back_publication(wiki_env, status, message):
    settings, sessions, state, space_id, directory = wiki_env
    knowledge_id = await publish(sessions, space_id)
    state["status"] = status
    async with sessions() as session:
        assert await sync_pending(session, settings) == 0
        sync = await session.get(KnowledgeSync, knowledge_id)
        assert sync.status == "failed" and message in sync.error
        assert "test-secret" not in sync.error
        assert (await session.get(KnowledgeItem, knowledge_id)).status == "published"
        with pytest.raises(LlmWikiError, match=message):
            await KnowledgeService(session).mcp_search(LibrarySearchInput(query="original"))
        assert await session.scalar(select(func.count(KnowledgeUsage.id))) == 0
        state["status"] = 200
        await KnowledgeService(session).resync(LibraryPrincipal())
        assert await sync_pending(session, settings) == 1
        assert (directory / f"{knowledge_id}.md").exists()


async def test_new_revision_during_rescan_remains_pending_and_converges(wiki_env):
    settings, sessions, state, space_id, directory = wiki_env
    knowledge_id = await publish(sessions, space_id)

    async def change_during_rescan():
        async with sessions() as other:
            await KnowledgeService(other).update_knowledge(
                knowledge_id, KnowledgePatch(content_md="newest"), LibraryPrincipal()
            )
        state["on_rescan"] = None

    state["on_rescan"] = change_during_rescan
    async with sessions() as session:
        await sync_pending(session, settings)
        session.expire_all()
        assert (await session.get(KnowledgeSync, knowledge_id)).status == "pending"
        await sync_pending(session, settings)
        assert "newest" in (directory / f"{knowledge_id}.md").read_text()
        session.expire_all()
        assert (await session.get(KnowledgeSync, knowledge_id)).status == "synced"


async def test_duplicate_workers_and_crash_retry(wiki_env):
    settings, sessions, state, space_id, directory = wiki_env
    knowledge_id = await publish(sessions, space_id)
    entered, release = asyncio.Event(), asyncio.Event()

    async def block_rescan():
        entered.set()
        await release.wait()

    state["on_rescan"] = block_rescan
    async with sessions() as first, sessions() as second:
        job = asyncio.create_task(sync_pending(first, settings))
        await entered.wait()
        assert await sync_pending(second, settings) == 0
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        state["on_rescan"] = None
        assert await sync_pending(second, settings) == 1
        assert (directory / f"{knowledge_id}.md").exists()


async def test_archive_failure_and_delete_tombstone_retry(wiki_env):
    settings, sessions, state, space_id, directory = wiki_env
    knowledge_id = await publish(sessions, space_id)
    async with sessions() as session:
        service = KnowledgeService(session)
        await sync_pending(session, settings)
        await service.archive(knowledge_id, LibraryPrincipal())
        state["status"] = 500
        await sync_pending(session, settings)
        assert (directory / f"{knowledge_id}.md").exists()
        await service.delete_knowledge(knowledge_id, LibraryPrincipal())
        await sync_pending(session, settings)
        state["status"] = 200
        await service.resync(LibraryPrincipal())
        await sync_pending(session, settings)
        assert not (directory / f"{knowledge_id}.md").exists()


async def test_scope_change_resyncs_descendants(wiki_env):
    settings, sessions, state, space_id, directory = wiki_env
    async with sessions() as session:
        service = KnowledgeService(session)
        child = await service.create_space(
            KnowledgeSpaceCreate(name="Child", parent_id=space_id), LibraryPrincipal()
        )
    knowledge_id = await publish(sessions, child.id)
    async with sessions() as session:
        service = KnowledgeService(session)
        await sync_pending(session, settings)
        await service.update_space(space_id, KnowledgeSpacePatch(access_scope="admin"), LibraryPrincipal())
        await sync_pending(session, settings)
        assert not (directory / f"{knowledge_id}.md").exists()


def test_atomic_write_failure_keeps_previous_file(tmp_path, monkeypatch):
    write_source(tmp_path, "KNOW_123", "old")

    def fail(*args):
        raise PermissionError(13, "permission denied")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(PermissionError):
        write_source(tmp_path, "KNOW_123", "new")
    assert (tmp_path / "KNOW_123.md").read_text() == "old"
    assert list(tmp_path.iterdir()) == [tmp_path / "KNOW_123.md"]


@pytest.mark.parametrize("path", ["../secret.md", "/wiki/a.md", "raw/sources/a.md", "wiki/../secret.md"])
async def test_read_rejects_non_wiki_paths(wiki_env, path):
    settings, _, state, _, _ = wiki_env
    with pytest.raises(LlmWikiError, match="resource_id"):
        await LlmWikiClient(settings).read(path)
    assert not state["calls"]


def test_migration_backfills_usage_and_published_sources(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "migration.db"
    env = {**os.environ, "ASTRA_DATABASE_URL": f"sqlite+aiosqlite:///{database}"}

    def migrate(*args):
        subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=backend,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    migrate("upgrade", "0018_merge_runtime_category")
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO knowledge_items "
            "(id,title,summary,content_md,status,tags,experience_data,created_by,updated_by,"
            "created_at,updated_at) VALUES "
            "('KNOW_old','old','','body','published','[]','{}','admin','admin',"
            "'2026-09-08 00:00:00','2026-09-08 00:00:00')"
        )
        conn.execute(
            "INSERT INTO knowledge_usage (knowledge_id,tool_name,action,result,created_at) "
            "VALUES ('KNOW_old','library_get','reference','{}','2026-09-08 00:00:00')"
        )
        conn.execute(
            "INSERT INTO knowledge_usage (tool_name,action,result,created_at) "
            "VALUES ('library_search','search','{\"knowledge_ids\":[\"KNOW_old\"]}',"
            "'2026-09-08 00:00:00')"
        )
    migrate("upgrade", "0019_library_llm_wiki")
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT resource_id,action FROM knowledge_usage ORDER BY id").fetchall() == [
            ("astra:KNOW_old", "read"),
            ("astra:KNOW_old", "search_hit"),
        ]
        assert conn.execute("SELECT knowledge_id,status FROM knowledge_sync").fetchone() == (
            "KNOW_old",
            "pending",
        )
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    migrate("downgrade", "0018_merge_runtime_category")
    migrate("upgrade", "0019_library_llm_wiki")


async def test_batch_publishes_rescan_once_and_reports_disk_failure(wiki_env, monkeypatch):
    settings, sessions, state, space_id, directory = wiki_env
    async with sessions() as session:
        service = KnowledgeService(session)
        ids = []
        for title in ("first", "second"):
            item = await service.create_knowledge(
                KnowledgeCreate(space_id=space_id, title=title, content_md=title), LibraryPrincipal()
            )
            ids.append(item.id)
        await service.batch_publish(ids, space_id, "verified", LibraryPrincipal())
        assert await sync_pending(session, settings) == 2
        assert (
            len([request for request in state["calls"] if request.url.path.endswith("/sources/rescan")]) == 1
        )
        await service.batch_archive(ids, LibraryPrincipal())

        def fail(*args):
            raise PermissionError(13, "denied")

        with monkeypatch.context() as patch:
            patch.setattr("app.library_sync.write_source", fail)
            assert await sync_pending(session, settings) == 0
        status = await service.service_status()
        assert not status.healthy and status.failed_count == 2
        assert "errno=13" in status.message
        await service.resync(LibraryPrincipal())
        assert await sync_pending(session, settings) == 2
        assert not list(directory.glob("*.md"))


async def test_disabled_service_and_all_feedback_types(wiki_env):
    settings, sessions, state, _, _ = wiki_env
    settings.llm_wiki_enabled = False
    async with sessions() as session:
        service = KnowledgeService(session)
        with pytest.raises(LlmWikiError, match="知识服务暂不可用：未启用"):
            await service.mcp_search(LibrarySearchInput(query="anything"))
        for kind in ("helpful", "incorrect", "outdated", "missing", "mismatch"):
            result = await service.mcp_feedback(
                LibraryFeedbackInput(resource_id="wiki/topic.md", feedback_type=kind)
            )
            assert result.feedback_type == kind
        assert await session.scalar(select(func.count(KnowledgeFeedback.id))) == 5
        assert not state["calls"]


async def test_mcp_expected_errors_are_not_masked_by_sdk(wiki_env):
    from mcp.server.mcpserver.exceptions import ToolError

    from app.mcp_server import mcp

    settings, _, _, _, _ = wiki_env
    settings.llm_wiki_enabled = False
    with pytest.raises(ToolError, match="知识服务暂不可用") as error:
        await mcp.call_tool("library_search", {"query": "timeout"})
    assert type(error.value) is ToolError
    with pytest.raises(ToolError, match="limit") as error:
        await mcp.call_tool("library_search", {"query": "timeout", "limit": 0})
    assert type(error.value) is ToolError


@pytest.mark.parametrize(
    "data",
    [
        {"ok": True, "result": {}},
        {"ok": True, "result": {"queue": {"tasks": [None]}}},
        {"ok": True, "result": {"queue": {"tasks": [{"status": "failed"}]}}},
    ],
)
async def test_rescan_rejects_invalid_or_failed_queue(wiki_env, monkeypatch, data):
    settings, _, _, _, _ = wiki_env

    async def response(*args, **kwargs):
        return data

    monkeypatch.setattr(LlmWikiClient, "request", response)
    with pytest.raises(LlmWikiError, match="知识服务暂不可用"):
        await LlmWikiClient(settings).rescan()
