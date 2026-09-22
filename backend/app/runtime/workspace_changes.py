"""Collect deterministic Workspace/Git facts."""

from __future__ import annotations

import asyncio
import shlex

from sqlalchemy import select

from app.config.settings import get_settings
from app.domain import ExecutionMode
from app.models import RuntimeSession
from app.runtime.environment import ExecutionEnvironmentRuntime
from app.runtime.session_connection import resolve_environment


async def _git(environment, workspace: str, *args: str) -> tuple[int, str]:
    """Return Git stdout without stripping porcelain-leading status bytes."""

    command = ["git", "-C", workspace, *args]
    if environment.mode == ExecutionMode.LOCAL:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output, _ = await process.communicate()
        return process.returncode, output.decode("utf-8", errors="replace")
    code, output, _ = await ExecutionEnvironmentRuntime(get_settings()).run_remote(
        environment, shlex.join(command)
    )
    return code, output


async def workspace_head_commit(environment, workspace: str) -> str | None:
    try:
        code, output = await _git(environment, workspace, "rev-parse", "HEAD")
        value = output.strip()
        return value if code == 0 and value else None
    except Exception:
        return None


def _status_path(line: str) -> tuple[str, str] | None:
    if len(line) < 4:
        return None
    status = line[:2]
    path = line[3:]
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return status, path


async def _task_baseline(session, task_id: str) -> str | None:
    return await session.scalar(
        select(RuntimeSession.workspace_base_commit)
        .where(
            RuntimeSession.task_id == task_id,
            RuntimeSession.workspace_base_commit.is_not(None),
        )
        .order_by(RuntimeSession.created_at, RuntimeSession.id)
        .limit(1)
    )


async def collect_workspace_changes(session, task) -> dict:
    """Return task-wide Git facts relative to the first Session baseline."""

    if not task.workspace or not task.execution_environment_snapshot:
        return {}
    try:
        environment = await resolve_environment(session, task)
        code, inside = await _git(environment, task.workspace, "rev-parse", "--is-inside-work-tree")
        if code or inside.strip().lower() != "true":
            return {}

        files: set[str] = set()
        added: set[str] = set()
        deleted: set[str] = set()

        code, porcelain = await _git(environment, task.workspace, "status", "--porcelain=v1")
        if code == 0:
            for line in porcelain.splitlines():
                parsed = _status_path(line)
                if not parsed:
                    continue
                status, path = parsed
                files.add(path)
                if "?" in status or "A" in status:
                    added.add(path)
                if "D" in status:
                    deleted.add(path)

        baseline = await _task_baseline(session, task.id)
        commits: list[str] = []
        if baseline:
            code, raw_commits = await _git(
                environment,
                task.workspace,
                "rev-list",
                "--reverse",
                "--max-count=200",
                f"{baseline}..HEAD",
            )
            if code == 0:
                commits = [line for line in raw_commits.splitlines() if line]
            diff_code, changed = await _git(
                environment,
                task.workspace,
                "diff",
                "--name-status",
                "--no-renames",
                f"{baseline}..HEAD",
            )
            if diff_code == 0:
                for line in changed.splitlines():
                    parts = line.split("\t", 1)
                    if len(parts) != 2:
                        continue
                    status, path = parts
                    if not path:
                        continue
                    files.add(path)
                    if status.startswith("A"):
                        added.add(path)
                    if status.startswith("D"):
                        deleted.add(path)

        if not files and not commits:
            return {}
        return {
            "baseline_commit": baseline,
            "changed_files": len(files),
            "added_files": len(added),
            "deleted_files": len(deleted),
            "files": sorted(files),
            "commits": commits,
        }
    except Exception:
        # Summary generation must never change a valid Session outcome merely
        # because the Workspace is no longer reachable.
        return {}
