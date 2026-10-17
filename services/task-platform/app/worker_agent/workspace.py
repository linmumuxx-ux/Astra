"""Prepare a task workspace on the Worker host."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_CONFIG_NAMES = (
    Path("opencode.json"),
    Path("opencode.jsonc"),
    Path(".opencode/opencode.json"),
    Path(".opencode/opencode.jsonc"),
)


def prepare_workspace_local(root: str, target: str, *, reuse_existing: bool = False) -> dict[str, str]:
    """Create the task directory the same way the SSH script does, without SSH."""

    source = Path(root)
    destination = Path(target)
    if not source.is_dir():
        raise RuntimeError("Workspace 不存在")
    if destination.is_symlink():
        raise RuntimeError("任务工作区不能是符号链接")
    created = False
    if destination.exists():
        if not destination.is_dir():
            raise RuntimeError("任务工作区不是目录")
    elif reuse_existing:
        raise RuntimeError("任务工作区不存在，请显式重新执行")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if _git_ok(source):
            physical = Path(os.path.realpath(destination))
            _worktree_add(source, physical)
            destination = physical
        else:
            destination.mkdir()
        created = True
    _validate_registered_worktree(source, destination)
    if created or not any((destination / name).exists() for name in _CONFIG_NAMES):
        for name in _CONFIG_NAMES:
            origin = source / name
            if origin.is_file():
                copied = destination / name
                copied.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, copied)
    return {"root": str(source), "target": str(destination), "created": str(created).lower()}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _git_ok(path: Path) -> bool:
    return _git(path, "rev-parse", "--show-toplevel").returncode == 0


def _common_dir(path: Path) -> str:
    result = _git(path, "rev-parse", "--git-common-dir")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "任务工作区准备失败")
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = path / common
    return os.path.realpath(common)


def _worktree_add(root: Path, target: Path) -> None:
    result = _git(root, "worktree", "add", "--detach", str(target), "HEAD")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "任务工作区准备失败")


def _validate_registered_worktree(source: Path, destination: Path) -> None:
    if _git_ok(destination):
        top = _git(destination, "rev-parse", "--show-toplevel").stdout.strip()
        if os.path.realpath(top) != os.path.realpath(destination):
            raise RuntimeError("任务工作区不是目录根")
    if not _git_ok(source):
        return
    if _common_dir(source) != _common_dir(destination):
        raise RuntimeError("任务工作区不属于当前仓库")
    physical = os.path.realpath(destination)
    listed = _git(source, "worktree", "list", "--porcelain").stdout.splitlines()
    if f"worktree {physical}" not in listed:
        raise RuntimeError("任务工作区未注册")
