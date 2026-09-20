"""Collect stable Workspace/Git facts for TaskSummary.

This module never asks the model to describe repository changes.  It only
returns facts that Git can prove for the task-bound Workspace.
"""

from __future__ import annotations

import asyncio
import shlex

from app.config.settings import get_settings
from app.domain import ExecutionMode
from app.runtime.environment import ExecutionEnvironmentRuntime
from app.runtime.session_connection import resolve_environment


async def _git(environment, workspace: str, *args: str) -> tuple[int, str]:
    command = ["git", "-C", workspace, *args]
    if environment.mode == ExecutionMode.LOCAL:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output, _ = await process.communicate()
        return process.returncode, output.decode(errors="replace").strip()
    code, output, _ = await ExecutionEnvironmentRuntime(get_settings()).run_remote(
        environment, shlex.join(command)
    )
    return code, output.strip()


def _status_path(line: str) -> tuple[str, str] | None:
    if len(line) < 4:
        return None
    status = line[:2]
    path = line[3:].strip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return status, path


async def collect_workspace_changes(session, task) -> dict:
    """Return changed file/commit facts, or an empty mapping when Git is unavailable."""

    if not task.workspace or not task.execution_environment_snapshot:
        return {}
    try:
        environment = await resolve_environment(session, task)
        code, inside = await _git(environment, task.workspace, "rev-parse", "--is-inside-work-tree")
        if code or inside.lower() != "true":
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

        # Task workspaces are detached worktrees. Commits created by the task are
        # normally reachable from HEAD but not from a named repository ref.
        code, raw_commits = await _git(
            environment,
            task.workspace,
            "rev-list",
            "--reverse",
            "--max-count=50",
            "HEAD",
            "--not",
            "--all",
        )
        commits = [line.strip() for line in raw_commits.splitlines() if line.strip()] if code == 0 else []
        for commit in commits:
            show_code, changed = await _git(
                environment,
                task.workspace,
                "show",
                "--format=",
                "--name-status",
                "--no-renames",
                commit,
            )
            if show_code:
                continue
            for line in changed.splitlines():
                parts = line.split("\t", 1)
                if len(parts) != 2:
                    continue
                status, path = parts[0].strip(), parts[1].strip()
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
