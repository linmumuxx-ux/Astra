import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.library_schemas import LibrarySubmitExperienceInput
from app.library_service import KnowledgeService
from app.models import (
    Base,
    DigitalEmployee,
    ExperienceEvidence,
    KnowledgeItem,
    OpenCodeExecutionEnvironment,
    RuntimeSession,
    Task,
)
from app.runtime.environment import environment_snapshot
from app.runtime.runtime_context import (
    generate_runtime_context,
    hash_runtime_context,
    runtime_context_id,
)


@asynccontextmanager
async def experience_session():
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
            title="Cache bug",
            task_type="ISSUE",
            status="RUNNING",
            employee_id="E1",
            current_session_id="ses_a",
            workspace="/tmp/ws",
            execution_environment_snapshot=environment_snapshot(environment),
        )
        token_a = generate_runtime_context()
        digest_a = hash_runtime_context(token_a)
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
                    last_message_id="a1",
                    runtime_context_hash=digest_a,
                    runtime_context_id=runtime_context_id(digest_a),
                ),
            ]
        )
        await session.commit()
        yield session, token_a
    await engine.dispose()


async def submit(service, token, *, title="缓存未刷新", content="清理缓存后重启", type_="fix"):
    return await service.mcp_submit_experience(
        LibrarySubmitExperienceInput(
            title=title,
            summary="处理步骤",
            content_md=content,
            experience_type=type_,
        ),
        runtime_context=token,
    )


async def test_running_submission_is_unverified_until_session_succeeds():
    async with experience_session() as (session, token):
        service = KnowledgeService(session)
        detail = await submit(service, token)
        item = await session.get(KnowledgeItem, detail.id)
        assert item.origin == "runtime"
        assert item.source_session_id == "ses_a"
        assert item.dedupe_key == "session:ses_a"
        assert item.fingerprint
        assert item.verification_status == "unverified"
        assert item.session_status_at_submission == "RUNNING"
        assert item.verified_at is None

        runtime_session = await session.get(RuntimeSession, "ses_a")
        runtime_session.status = "SUCCEEDED"
        runtime_session.last_message_id = "a-final"
        await session.commit()

        assert await service.reconcile_session_verification("ses_a") == 1
        item = await session.get(KnowledgeItem, detail.id)
        assert item.verification_status == "verified"
        assert item.verification_session_status == "SUCCEEDED"
        assert item.verification_message_id == "a-final"
        assert item.session_last_message_id_at_verification == "a-final"
        assert item.verified_at is not None
        # Reconcile is idempotent.
        assert await service.reconcile_session_verification("ses_a") == 0


async def test_failed_source_session_never_verifies():
    async with experience_session() as (session, token):
        service = KnowledgeService(session)
        detail = await submit(service, token)
        runtime_session = await session.get(RuntimeSession, "ses_a")
        runtime_session.status = "FAILED"
        await session.commit()
        assert await service.reconcile_session_verification("ses_a") == 0
        item = await session.get(KnowledgeItem, detail.id)
        assert item.verification_status == "unverified" and item.verified_at is None


async def test_verified_experience_is_not_downgraded_after_continue_failure():
    async with experience_session() as (session, token):
        service = KnowledgeService(session)
        runtime_session = await session.get(RuntimeSession, "ses_a")
        runtime_session.status = "SUCCEEDED"
        runtime_session.last_message_id = "a1"
        await session.commit()
        detail = await submit(service, token)
        item = await session.get(KnowledgeItem, detail.id)
        assert item.verification_status == "verified"

        runtime_session.status = "FAILED"
        await session.commit()
        assert await service.reconcile_session_verification("ses_a") == 0
        item = await session.get(KnowledgeItem, detail.id)
        assert item.verification_status == "verified"
        assert item.verification_session_status == "SUCCEEDED"


async def test_fingerprint_dedupes_same_experience_in_one_session():
    async with experience_session() as (session, token):
        service = KnowledgeService(session)
        first = await submit(service, token)
        second = await submit(service, token, content="清理缓存后重启")
        assert first.id == second.id
        assert await session.scalar(select(func.count()).select_from(KnowledgeItem)) == 1

        other = await submit(service, token, title="另一个问题", content="另一套处理")
        assert other.id != first.id
        assert await session.scalar(select(func.count()).select_from(KnowledgeItem)) == 2


async def test_manual_experience_dedupes_without_a_session():
    async with experience_session() as (session, _token):
        service = KnowledgeService(session)
        first = await service.mcp_submit_experience(
            LibrarySubmitExperienceInput(title="人工经验", content_md="同样内容")
        )
        second = await service.mcp_submit_experience(
            LibrarySubmitExperienceInput(title="人工经验", content_md="同样内容")
        )
        assert first.id == second.id
        item = await session.get(KnowledgeItem, first.id)
        assert item.origin == "manual"
        assert item.dedupe_key == "manual:mcp"


async def test_evidence_keeps_session_provenance():
    async with experience_session() as (session, token):
        service = KnowledgeService(session)
        detail = await service.mcp_submit_experience(
            LibrarySubmitExperienceInput(
                title="证据来源",
                content_md="内容",
                evidence=[
                    {
                        "evidence_type": "message",
                        "message_id": "a1",
                        "part_id": "p1",
                        "file_path": "src/cache.py",
                        "diff_hash": "deadbeef",
                    }
                ],
            ),
            runtime_context=token,
        )
        evidence = await session.scalar(
            select(ExperienceEvidence).where(ExperienceEvidence.knowledge_id == detail.id)
        )
        assert evidence.source_session_id == "ses_a"
        assert evidence.message_id == "a1"
        assert evidence.part_id == "p1"
        assert evidence.file_path == "src/cache.py"
        assert evidence.diff_hash == "deadbeef"
        assert evidence.captured_at is not None

def test_published_knowledge_survives_task_deletion():
    from app.database import SessionLocal
    from app.main import app
    from app.models import DigitalEmployee, Task

    suffix = uuid4().hex[:8]
    employee_id = f"E-DEL-{suffix}"
    task_id = f"T-DEL-{suffix}"
    knowledge_id = f"KNOW-DEL-{suffix}"

    async def setup():
        async with SessionLocal() as session:
            session.add(DigitalEmployee(id=employee_id, name="Del", role="build", status="IDLE"))
            session.add(
                Task(
                    id=task_id,
                    title="待删除任务",
                    task_type="ISSUE",
                    status="SUCCEEDED",
                    employee_id=employee_id,
                )
            )
            session.add(
                KnowledgeItem(
                    id=knowledge_id,
                    title="长期经验",
                    type="experience",
                    summary="摘要",
                    content_md="内容",
                    status="published",
                    verification_status="verified",
                    created_by="reviewer",
                    updated_by="reviewer",
                    source_task_id=task_id,
                    source_ref_snapshot={"task_title": "待删除任务"},
                )
            )
            await session.commit()

    async def read():
        async with SessionLocal() as session:
            item = await session.get(KnowledgeItem, knowledge_id)
            return item.source_task_id, item.source_ref_snapshot

    with TestClient(app) as client:
        asyncio.run(setup())
        assert client.delete(f"/api/tasks/{task_id}").status_code == 200
    source_task_id, snapshot = asyncio.run(read())
    assert source_task_id is None
    assert snapshot == {"task_title": "待删除任务"}
