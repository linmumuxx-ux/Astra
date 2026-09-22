import json
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config.settings import Settings
from app.library_schemas import LibraryResource, LibrarySubmitExperienceInput
from app.library_service import KnowledgeService
from app.models import (
    Base,
    DigitalEmployee,
    KnowledgeItem,
    KnowledgeUsage,
    OpenCodeExecutionEnvironment,
    RuntimeSession,
    Task,
)
from app.runtime.environment import environment_snapshot
from app.runtime.opencode_config import remote_runtime_config_content, write_local_runtime_config
from app.runtime.runtime_context import (
    RuntimeContextError,
    generate_runtime_context,
    hash_runtime_context,
    resolve_runtime_context,
    runtime_context_id,
)


@asynccontextmanager
async def context_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        employee = DigitalEmployee(id="E1", name="Engineer", role="build", status="IDLE")
        environment = OpenCodeExecutionEnvironment(
            employee_id="E1", mode="LOCAL", name="test", workspace_root="/tmp/ws", status="AVAILABLE"
        )
        session.add_all([employee, environment])
        await session.flush()
        task = Task(
            id="T1",
            title="Task",
            task_type="ISSUE",
            status="RUNNING",
            employee_id="E1",
            current_session_id="ses_a",
            workspace="/tmp/ws",
            execution_environment_snapshot=environment_snapshot(environment),
        )
        token = generate_runtime_context()
        digest = hash_runtime_context(token)
        session.add_all(
            [
                task,
                RuntimeSession(
                    id="ses_a",
                    task_id="T1",
                    employee_id="E1",
                    workspace="/tmp/ws",
                    environment=environment_snapshot(environment),
                    status="RUNNING",
                    runtime_context_hash=digest,
                    runtime_context_id=runtime_context_id(digest),
                ),
            ]
        )
        await session.commit()
        yield session, token
    await engine.dispose()


async def test_correct_token_resolves_origin():
    async with context_session() as (session, token):
        context = await resolve_runtime_context(session, token)
    assert context.task_id == "T1"
    assert context.session_id == "ses_a"
    assert context.employee_id == "E1"
    assert context.runtime_context_id == hash_runtime_context(token)[:12]


async def test_missing_and_wrong_tokens_are_rejected():
    async with context_session() as (session, _token):
        with pytest.raises(RuntimeContextError):
            await resolve_runtime_context(session, None)
        with pytest.raises(RuntimeContextError):
            await resolve_runtime_context(session, "ctx_not-a-real-token")
        with pytest.raises(RuntimeContextError):
            await resolve_runtime_context(session, "ses_a")


async def test_deleted_session_token_is_rejected():
    async with context_session() as (session, token):
        row = await session.get(RuntimeSession, "ses_a")
        await session.delete(row)
        await session.commit()
        with pytest.raises(RuntimeContextError):
            await resolve_runtime_context(session, token)


async def test_old_session_token_resolves_old_not_current():
    async with context_session() as (session, token_a):
        token_b = generate_runtime_context()
        digest_b = hash_runtime_context(token_b)
        session.add(
            RuntimeSession(
                id="ses_b",
                task_id="T1",
                employee_id="E1",
                workspace="/tmp/ws",
                environment={},
                status="RUNNING",
                runtime_context_hash=digest_b,
                runtime_context_id=runtime_context_id(digest_b),
            )
        )
        task = await session.get(Task, "T1")
        task.current_session_id = "ses_b"
        old = await session.get(RuntimeSession, "ses_a")
        old.superseded_by = "ses_b"
        await session.commit()

        context = await resolve_runtime_context(session, token_a)
        assert context.session_id == "ses_a"

        current = await resolve_runtime_context(session, token_b)
        assert current.session_id == "ses_b"


async def test_runtime_submission_ignores_agent_supplied_identity():
    async with context_session() as (session, token):
        detail = await KnowledgeService(session).mcp_submit_experience(
            LibrarySubmitExperienceInput(
                title="升级后缓存未刷新",
                summary="清理缓存后重启服务",
                content_md="## 处理\n\n清理缓存。",
                source_employee_id="FORGED",
                source_task_id="FORGED_TASK",
            ),
            runtime_context=token,
        )
        item = await session.get(KnowledgeItem, detail.id)
    assert item.source_task_id == "T1"
    assert item.source_employee_id == "E1"
    assert item.source_session_id == "ses_a"


async def test_runtime_library_read_records_task_session_and_knowledge(monkeypatch):
    async with context_session() as (session, token):
        item = KnowledgeItem(
            id="KNOW_READ_1",
            title="参数升级规则",
            type="rule",
            summary="升级规则",
            content_md="# 参数升级规则",
            status="published",
            verification_status="verified",
            tags=[],
            origin="manual",
            scope={},
            source_ref_snapshot={},
            experience_data={},
            created_by="test",
            updated_by="test",
        )
        session.add(item)
        await session.commit()

        async def fake_read(_client, resource_id):
            return LibraryResource(
                resource_id=resource_id,
                path=resource_id,
                content_md=(
                    "---\n"
                    "astra_knowledge_id: KNOW_READ_1\n"
                    "---\n\n"
                    "# 参数升级规则"
                ),
            )

        monkeypatch.setattr("app.library_service.LlmWikiClient.read", fake_read)
        await KnowledgeService(session).mcp_get(
            "wiki/parameter-upgrade.md",
            runtime_context=token,
        )

        usage = await session.scalar(
            select(KnowledgeUsage).where(KnowledgeUsage.action == "read")
        )
        assert usage.knowledge_id == "KNOW_READ_1"
        assert usage.employee_id == "E1"
        assert usage.task_id == "T1"
        assert usage.session_id == "ses_a"


async def test_invalid_token_never_echoes_the_token(caplog):
    secret = "ctx_supersecretvalue"
    async with context_session() as (session, _token):
        with caplog.at_level("DEBUG"):
            with pytest.raises(RuntimeContextError) as error:
                await resolve_runtime_context(session, secret)
    assert secret not in str(error.value)
    assert secret not in caplog.text


def test_local_runtime_config_is_written_outside_the_worktree(tmp_path):
    settings = Settings(runtime_dir=tmp_path / "runtime", workspace_root=tmp_path / "worktree")
    path = write_local_runtime_config(settings, "E1")
    assert path.exists()
    assert path.parent == (tmp_path / "runtime" / "opencode").resolve()
    assert not str(path).startswith(str((tmp_path / "worktree").resolve()))
    payload = path.read_text(encoding="utf-8")
    assert '"astra_library"' in payload


def test_remote_runtime_config_reaches_knowledge_over_http_mcp():
    settings = Settings(_env_file=None, mcp_api_key="secret")
    payload = json.loads(remote_runtime_config_content(settings, "http://127.0.0.1:8201/mcp"))
    server = payload["mcp"]["astra_library"]
    assert server["type"] == "remote"
    assert server["url"] == "http://127.0.0.1:8201/mcp"
    assert server["headers"]["Authorization"] == "Bearer secret"
    assert payload["permission"]["astra_library_*"] == "allow"


async def test_runtime_session_context_hash_is_unique():
    async with context_session() as (session, token):
        digest = hash_runtime_context(token)
        duplicate = await session.scalar(
            select(RuntimeSession).where(RuntimeSession.runtime_context_hash == digest)
        )
        assert duplicate is not None