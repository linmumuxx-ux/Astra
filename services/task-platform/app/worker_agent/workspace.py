"""Prepare a task workspace on the Worker host."""

from __future__ import annotations

import shutil
from pathlib import Path


def prepare_workspace_local(root: str, target: str, *, reuse_existing: bool = False) -> dict[str, str]:
    source = Path(root)
    destination = Path(target)
    if destination.is_symlink():
        raise RuntimeError("任务工作区不能是符号链接")
    if not source.is_dir():
        raise RuntimeError("Workspace 不存在")
    created = False
    if destination.exists():
        if not destination.is_dir():
            raise RuntimeError("任务工作区不是目录")
    elif reuse_existing:
        raise RuntimeError("任务工作区不存在，请显式重新执行")
    else:
        destination.mkdir(parents=True)
        created = True
    names = (
        Path("opencode.json"),
        Path("opencode.jsonc"),
        Path(".opencode/opencode.json"),
        Path(".opencode/opencode.jsonc"),
    )
    if created or not any((destination / name).exists() for name in names):
        for name in names:
            origin = source / name
            if origin.is_file():
                copied = destination / name
                copied.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, copied)
    return {"root": str(source), "target": str(destination), "created": str(created).lower()}
