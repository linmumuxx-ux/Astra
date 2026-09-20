"""Durable source synchronization, dispatched by the existing Celery beat/worker."""

import os
import re
import tempfile
from pathlib import Path
from uuid import uuid4

import yaml
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.llm_wiki import LlmWikiClient, LlmWikiError
from app.models import KnowledgeItem, KnowledgeSync, utcnow


async def mark_for_sync(session: AsyncSession, knowledge_id: str) -> None:
    # Both supported databases provide atomic upsert, including concurrent first publication.
    if session.bind.dialect.name == "mysql":
        from sqlalchemy.dialects.mysql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    values = dict(
        knowledge_id=knowledge_id, revision=uuid4().hex, status="pending", requested_at=utcnow(), error=None
    )
    statement = insert(KnowledgeSync).values(**values)
    changes = {key: value for key, value in values.items() if key != "knowledge_id"}
    if session.bind.dialect.name == "mysql":
        statement = statement.on_duplicate_key_update(**changes)
    else:
        statement = statement.on_conflict_do_update(index_elements=["knowledge_id"], set_=changes)
    await session.execute(statement)


def source_markdown(item: KnowledgeItem) -> str:
    metadata = dict(
        astra_knowledge_id=item.id,
        title=item.title,
        type=item.type,
        space_id=item.space_id,
        tags=item.tags or [],
        updated_at=item.updated_at.isoformat(),
    )
    return (
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
        + "---\n\n"
        + f"# {item.title}\n\n{item.summary}\n\n{item.content_md}\n"
    )


def write_source(directory: Path, knowledge_id: str, content: str | None) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", knowledge_id):
        raise LlmWikiError("知识同步失败：knowledge_id 不是安全的稳定文件名")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{knowledge_id}.md"
    if content is None:
        target.unlink(missing_ok=True)
        return
    # A hidden non-Markdown temp file cannot be ingested as a partial source.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, prefix=".astra-", suffix=".tmp", delete=False
        ) as stream:
            temp_path = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _try_lock_file(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        if handle.read(1) == b"":
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


async def sync_pending(session: AsyncSession, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    if not settings.llm_wiki_enabled:
        return 0
    client = LlmWikiClient(settings)
    rows = (
        await session.execute(
            select(KnowledgeSync.knowledge_id, KnowledgeSync.revision)
            .where(KnowledgeSync.status == "pending")
            .order_by(KnowledgeSync.requested_at)
            .limit(100)
        )
    ).all()
    await session.commit()
    if not rows:
        return 0
    # The deployment shares one filesystem. An OS lock covers Celery duplicates and
    # manual runs, and is released automatically on process termination. No lease can
    # expire while an old worker is still writing. Do not block the worker event loop.
    lock_path = settings.resolved_runtime_dir / "library-sync.lock"
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = lock_path.open("a+b")
    except OSError as exc:
        for knowledge_id, revision in rows:
            await _finish(
                session, knowledge_id, revision, f"知识同步失败：无法打开同步锁（errno={exc.errno}）"
            )
        return 0
    with lock_file as lock:
        try:
            _try_lock_file(lock)
        except OSError:
            return 0
        try:
            try:
                await client.verify_project()
            except LlmWikiError as exc:
                for knowledge_id, revision in rows:
                    await _finish(session, knowledge_id, revision, str(exc))
                return 0

            directory = (
                settings.absolute_path(settings.llm_wiki_project_path)
                / "raw"
                / "sources"
                / "astra"
            )
            written = []
            for knowledge_id, _ in rows:
                # Read after taking the lock; never replay an old serialized Knowledge payload.
                row = await session.scalar(
                    select(KnowledgeSync)
                    .where(KnowledgeSync.knowledge_id == knowledge_id)
                    .execution_options(populate_existing=True)
                )
                if row is None or row.status != "pending":
                    continue
                revision = row.revision
                item = await session.scalar(
                    select(KnowledgeItem)
                    .where(KnowledgeItem.id == knowledge_id)
                    .execution_options(populate_existing=True)
                )
                content = None
                if item is not None and item.status == "published":
                    from app.library_service import KnowledgeService, LibraryPrincipal

                    visible = await KnowledgeService(session)._visible_space_ids(
                        LibraryPrincipal(user_id="mcp", role="viewer")
                    )
                    if item.space_id is None or item.space_id in visible:
                        content = source_markdown(item)
                await session.commit()

                error = None
                try:
                    write_source(directory, knowledge_id, content)
                except LlmWikiError as exc:
                    error = str(exc)
                except OSError as exc:
                    error = f"知识同步失败：raw source 写入或删除失败（errno={exc.errno}）"
                if error:
                    await _finish(session, knowledge_id, revision, error)
                else:
                    written.append((knowledge_id, revision))

            if not written:
                return 0
            error = None
            try:
                await client.rescan()
            except LlmWikiError as exc:
                error = str(exc)
            for knowledge_id, revision in written:
                await _finish(session, knowledge_id, revision, error)
            return len(written) if error is None else 0
        finally:
            _unlock_file(lock)


async def _finish(session: AsyncSession, knowledge_id: str, revision: str, error: str | None) -> None:
    values = dict(status="failed" if error else "synced", error=error)
    if error is None:
        values["synced_at"] = utcnow()
    # A newer commit keeps its pending state even when this in-flight rescan finishes.
    await session.execute(
        update(KnowledgeSync)
        .where(
            KnowledgeSync.knowledge_id == knowledge_id,
            KnowledgeSync.revision == revision,
        )
        .values(**values)
    )
    await session.commit()
