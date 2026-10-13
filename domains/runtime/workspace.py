"""TaskExecution 的独立 Git worktree，重用必须重新核验注册和仓库归属。

提取自 backend/app/runtime/session_connection.py；删除 Employee 路径和旧 Settings。
不做业务授权：调用前必须验证有效 Workspace Grant、Worker lease 和资产锁。
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from domains.runtime.errors import WorkspaceUnsafe

_IDENTIFIER = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}")
_CONFIG_NAMES = (
    Path("opencode.json"),
    Path("opencode.jsonc"),
    Path(".opencode/opencode.json"),
    Path(".opencode/opencode.jsonc"),
)


@dataclass(frozen=True, slots=True)
class WorkspaceBinding:
    project_root: str
    directory: str
    task_id: str
    execution_id: str
    base_commit: str


async def _git(
    args: list[str], *, timeout_seconds: float = 30, env=None, input_bytes=None, raw_output=False
) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE if input_bytes is not None else None,
        env=env,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(input_bytes), timeout_seconds)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise WorkspaceUnsafe("Git 控制请求超时；请核验 worktree 注册后重试") from None
    decoded = out.decode(errors="strict")
    return (
        process.returncode or 0,
        decoded if raw_output else decoded.strip(),
        err.decode(errors="replace").strip(),
    )


def _canonical(path: Path, *, must_exist: bool = True) -> Path:
    absolute = path.absolute()
    if any(part == ".." for part in absolute.parts):
        raise WorkspaceUnsafe("工作区路径不得包含上级引用")
    try:
        resolved = absolute.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise WorkspaceUnsafe("工作区路径不存在或无法解析") from exc
    # 不只检查末级路径，防止借用父目录的 symlink 越过 Workspace Grant。
    if absolute != resolved:
        raise WorkspaceUnsafe("工作区路径及其父目录不得经过符号链接")
    if must_exist and not resolved.is_dir():
        raise WorkspaceUnsafe("工作区必须是目录")
    return resolved


async def _common_dir(path: Path) -> Path:
    code, out, _ = await _git(["-C", str(path), "rev-parse", "--git-common-dir"])
    if code or not out:
        raise WorkspaceUnsafe("工程不是有效 Git 仓库")
    candidate = Path(out)
    if not candidate.is_absolute():
        candidate = path / candidate
    return candidate.resolve(strict=True)


async def _verify_worktree(project: Path, target: Path) -> None:
    target = _canonical(target)
    code, top, _ = await _git(["-C", str(target), "rev-parse", "--show-toplevel"])
    if code or Path(top).resolve() != target:
        raise WorkspaceUnsafe("工作区不是 Git worktree 目录根")
    if await _common_dir(project) != await _common_dir(target):
        raise WorkspaceUnsafe("工作区不属于批准的工程仓库")
    code, listing, _ = await _git(["-C", str(project), "worktree", "list", "--porcelain", "-z"])
    registered = {
        Path(field[len("worktree ") :]).resolve()
        for field in listing.split("\x00")
        if field.startswith("worktree ")
    }
    if code or target not in registered:
        raise WorkspaceUnsafe("工作区未注册在批准工程的 Git worktree 列表")
    if target == project:
        raise WorkspaceUnsafe("TaskExecution 不得复用工程主工作区")


def _inherit_config(project: Path, target: Path) -> None:
    """保留任务自己的 OpenCode 配置；首次工作区复制工程提供的配置。"""
    if any((target / name).exists() for name in _CONFIG_NAMES):
        return
    for name in _CONFIG_NAMES:
        source, destination = project / name, target / name
        if source.is_symlink():
            raise WorkspaceUnsafe("OpenCode 工程配置不得通过符号链接读取")
        if not source.is_file():
            continue
        # .opencode 父目录、目标配置也必须处于当前 worktree 内。
        if source.resolve() != source or destination.resolve() != destination:
            raise WorkspaceUnsafe("OpenCode 配置路径越过工程或工作区边界")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


async def prepare_task_workspace(
    *,
    project_root: str,
    workspace_root: str,
    task_id: str,
    execution_id: str,
    base_ref: str = "HEAD",
    reuse: bool = False,
    inherit_project_config: bool = True,
) -> WorkspaceBinding:
    """每个执行尝试有固定目录；恢复不创建缺失目录、不清理残留文件、不修改 HEAD。"""
    if not _IDENTIFIER.fullmatch(task_id) or not _IDENTIFIER.fullmatch(execution_id):
        raise WorkspaceUnsafe("任务与执行索引不能成为任意路径")
    if not base_ref or base_ref.startswith("-"):
        raise WorkspaceUnsafe("工程基线必须是明确 Git revision")
    if reuse and not re.fullmatch(r"[0-9a-f]{40,64}", base_ref):
        raise WorkspaceUnsafe("恢复必须使用已保存的基线 commit，不能跟随当前 HEAD")
    project = _canonical(Path(project_root))
    storage = _canonical(Path(workspace_root))
    code, project_top, _ = await _git(["-C", str(project), "rev-parse", "--show-toplevel"])
    if code or Path(project_top).resolve() != project:
        raise WorkspaceUnsafe("工程授权必须指向 Git 仓库目录根")
    common = await _common_dir(project)
    if storage == project or storage == common or common in storage.parents:
        raise WorkspaceUnsafe("工作区根目录不能是工程目录或 Git 元数据目录")
    target = _canonical(storage / task_id / execution_id, must_exist=False)
    if storage not in target.parents or project == target:
        raise WorkspaceUnsafe("执行工作区越过授权根目录")
    code, commit, _ = await _git(["-C", str(project), "rev-parse", "--verify", f"{base_ref}^{{commit}}"])
    if code or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise WorkspaceUnsafe("无法核验工程基线 commit")
    exists = target.exists()
    if reuse:
        if not exists:
            raise WorkspaceUnsafe("已绑定工作区丢失；必须先对账，不能自动重建")
        await _verify_worktree(project, target)
    elif exists:
        raise WorkspaceUnsafe("执行工作区已存在；须通过已保存绑定显式恢复")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        code, _, _ = await _git(["-C", str(project), "worktree", "add", "--detach", str(target), commit])
        if code:
            raise WorkspaceUnsafe("Git worktree 创建失败；请核验注册和残留目录")
        await _verify_worktree(project, target)
    if inherit_project_config:
        _inherit_config(project, target)
    return WorkspaceBinding(str(project), str(target), task_id, execution_id, commit)


async def verify_workspace_binding(binding: WorkspaceBinding, *, workspace_root: str) -> None:
    """恢复时验证固定执行目录和原 commit 可查；不会把当前 HEAD 当作任务完成证据。"""
    project = _canonical(Path(binding.project_root))
    storage = _canonical(Path(workspace_root))
    if not _IDENTIFIER.fullmatch(binding.task_id) or not _IDENTIFIER.fullmatch(binding.execution_id):
        raise WorkspaceUnsafe("已保存的工作区业务索引无效")
    expected = storage / binding.task_id / binding.execution_id
    if Path(binding.directory) != expected:
        raise WorkspaceUnsafe("工作区路径与已保存的执行索引不符")
    await _verify_worktree(project, expected)
    code, _, _ = await _git(["-C", str(project), "cat-file", "-e", f"{binding.base_commit}^{{commit}}"])
    if code:
        raise WorkspaceUnsafe("已绑定基线 commit 不可核验")


async def capture_workspace_artifact(
    binding: WorkspaceBinding,
    *,
    workspace_root: str,
    captured_at: int,
    max_bytes: int = 128 * 1024 * 1024,
    max_files: int = 10000,
) -> str:
    """保存 tracked/非忽略文件的 Git 对象，不改变工程分支、HEAD 或调用者 index。

    临时 index 禁用外部过滤器/签名/hooks，防止归档步骤执行未授权的项目脚本。
    执行 UUID 对应的 ref 只能首次建立；重跑必须得到相同内容，不能覆盖旧产物。
    """
    await verify_workspace_binding(binding, workspace_root=workspace_root)
    target = Path(binding.directory)
    with tempfile.TemporaryDirectory(prefix="astra-v1-artifact-index-") as temporary:
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(
            {
                "GIT_INDEX_FILE": str(Path(temporary) / "index"),
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "Astra Artifact",
                "GIT_COMMITTER_NAME": "Astra Artifact",
                "GIT_AUTHOR_EMAIL": "artifact@astra.invalid",
                "GIT_COMMITTER_EMAIL": "artifact@astra.invalid",
                "GIT_AUTHOR_DATE": f"@{captured_at} +0000",
                "GIT_COMMITTER_DATE": f"@{captured_at} +0000",
            }
        )
        git = ["-C", str(target), "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull]
        _, filters, _ = await _git(
            git + ["config", "--name-only", "--get-regexp", r"^filter\..*\.(clean|process|smudge|required)$"],
            env=env,
        )
        for name in filters.splitlines():
            git += ["-c", name + ("=false" if name.endswith(".required") else "=")]

        async def run(args, *, input_bytes=None, raw_output=False):
            code, out, _ = await _git(git + args, env=env, input_bytes=input_bytes, raw_output=raw_output)
            if code:
                raise WorkspaceUnsafe("无法建立或核验不可变工程产物；保留原工作区等待对账")
            return out

        await run(["read-tree", "HEAD"])
        listing = await run(["ls-files", "--cached", "--others", "--exclude-standard", "-z"], raw_output=True)
        paths = [value for value in listing.split("\0") if value]
        if len(paths) > max_files:
            raise WorkspaceUnsafe("工程产物文件数量超过部署边界，需人工确认")
        total = 0
        for relative in paths:
            path = target / relative
            if path.parent.resolve() != path.parent:
                raise WorkspaceUnsafe("产物父目录不能通过符号链接越界")
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                continue  # tracked 删除也属于明确的 Git 产物变化。
            if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)):
                raise WorkspaceUnsafe("工程产物包含特殊设备或管道，不能归档")
            total += metadata.st_size
        if total > max_bytes:
            raise WorkspaceUnsafe("工程产物超过部署容量边界，需人工确认")
        await run(["add", "--all", "--", "."])
        tree = await run(["write-tree"])
        # 归档期间的写入或新增文件不可被静默丢失。
        await run(["diff", "--quiet", "--no-ext-diff", "--no-textconv"])
        if await run(["ls-files", "--others", "--exclude-standard"]):
            raise WorkspaceUnsafe("归档期间工作区出现新文件，须先停止写入再核验")
        commit = await run(
            ["-c", "commit.gpgsign=false", "commit-tree", tree, "-p", binding.base_commit],
            input_bytes=f"Astra execution artifact {binding.execution_id}\n".encode(),
        )
        ref = f"refs/astra/artifacts/{binding.execution_id}"
        code, current, _ = await _git(git + ["rev-parse", "--verify", ref], env=env)
        if code == 0:
            if current != commit:
                raise WorkspaceUnsafe("同一执行的已保存产物不可被修改或覆盖")
        else:
            await run(["update-ref", ref, commit, "0" * len(commit)])
        return commit
