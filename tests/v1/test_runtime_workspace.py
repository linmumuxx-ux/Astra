"""在临时 Git 仓库运行真实文件/worktree 检查，不连接 OpenCode 模型。"""

import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from domains.runtime.errors import WorkspaceUnsafe
from domains.runtime.workspace import (
    capture_workspace_artifact,
    prepare_task_workspace,
    verify_workspace_binding,
)

pytestmark = pytest.mark.asyncio


async def git(path, *args):
    process = await asyncio.create_subprocess_exec(
        "git", "-C", str(path), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await process.communicate()
    assert process.returncode == 0, err.decode()
    return out.decode().strip()


@pytest.fixture
async def project(tmp_path):
    # macOS /var 本身是 symlink；授权使用物理目录，便于核验后续目录未被换成链接。
    base = tmp_path.resolve()
    repository, storage = base / "repo", base / "workspaces"
    repository.mkdir()
    storage.mkdir()
    await git(repository, "init", "-q")
    (repository / "readme.txt").write_text("原始内容\n")
    await git(repository, "add", ".")
    await git(
        repository,
        "-c",
        "user.name=Astra Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "baseline",
    )
    return repository, storage


async def prepare(project, execution_id="execution-1", **kwargs):
    repository, storage = project
    return await prepare_task_workspace(
        project_root=str(repository),
        workspace_root=str(storage),
        task_id="task-1",
        execution_id=execution_id,
        **kwargs,
    )


async def test_parallel_executions_are_isolated_and_recovery_preserves_changes(project):
    first, second = await asyncio.gather(prepare(project), prepare(project, "execution-2"))
    from pathlib import Path

    Path(first.directory, "readme.txt").write_text("未提交的任务工作\n")
    assert Path(second.directory, "readme.txt").read_text() == "原始内容\n"
    recovered = await prepare(project, reuse=True, base_ref=first.base_commit)
    assert recovered.directory == first.directory
    assert Path(first.directory, "readme.txt").read_text() == "未提交的任务工作\n"
    await verify_workspace_binding(recovered, workspace_root=str(project[1]))
    with pytest.raises(WorkspaceUnsafe):
        await prepare(project)


async def test_existing_non_worktree_and_missing_binding_are_rejected(project):
    repository, storage = project
    (storage / "task-1" / "execution-1").mkdir(parents=True)
    with pytest.raises(WorkspaceUnsafe):
        await prepare(project, reuse=True, base_ref=await git(repository, "rev-parse", "HEAD"))
    with pytest.raises(WorkspaceUnsafe):
        await prepare(project, "missing", reuse=True, base_ref=await git(repository, "rev-parse", "HEAD"))


async def test_another_repositories_worktree_cannot_be_reused(project, tmp_path):
    repository, storage = project
    other = tmp_path.resolve() / "other"
    await git(repository, "clone", "-q", str(repository), str(other))
    (storage / "task-1").mkdir()
    await git(other, "worktree", "add", "--detach", str(storage / "task-1" / "execution-1"), "HEAD")
    with pytest.raises(WorkspaceUnsafe):
        await prepare(project, reuse=True, base_ref=await git(repository, "rev-parse", "HEAD"))


async def test_symlink_parent_cannot_bypass_workspace_boundary(project, tmp_path):
    repository, storage = project
    outside = tmp_path.resolve() / "outside"
    outside.mkdir()
    (storage / "task-1").symlink_to(outside, target_is_directory=True)
    with pytest.raises(WorkspaceUnsafe):
        await prepare(project)
    assert list(outside.iterdir()) == []


async def test_task_config_is_inherited_once_then_preserved(project):
    repository, storage = project
    (repository / "opencode.json").write_text('{"agent":{"test":{}}}')
    binding = await prepare(project)
    from pathlib import Path

    config = Path(binding.directory, "opencode.json")
    assert config.read_text() == '{"agent":{"test":{}}}'
    config.write_text('{"agent":{"task-specific":{}}}')
    (repository / "opencode.json").write_text('{"agent":{"changed-project":{}}}')
    await prepare(project, reuse=True, base_ref=binding.base_commit)
    assert config.read_text() == '{"agent":{"task-specific":{}}}'


async def test_forged_workspace_binding_or_path_traversal_is_rejected(project):
    binding = await prepare(project)
    with pytest.raises(WorkspaceUnsafe):
        await verify_workspace_binding(replace(binding, execution_id="other"), workspace_root=str(project[1]))
    with pytest.raises(WorkspaceUnsafe):
        await prepare(project, "../other")


async def test_recovery_requires_original_commit_even_after_main_project_advances(project):
    repository, storage = project
    binding = await prepare(project)
    (repository / "next.txt").write_text("后续主工程变化")
    await git(repository, "add", ".")
    await git(
        repository,
        "-c",
        "user.name=Astra Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "advance",
    )
    with pytest.raises(WorkspaceUnsafe, match="基线"):
        await prepare(project, reuse=True)
    restored = await prepare(project, reuse=True, base_ref=binding.base_commit)
    assert restored.base_commit == binding.base_commit
    from pathlib import Path

    assert not Path(restored.directory, "next.txt").exists()


async def test_immutable_artifact_preserves_changes_and_original_index_for_new_attempt(project):
    first = await prepare(project)
    path = Path(first.directory)
    (path / "readme.txt").write_text("已完成但未提交的工作\n")
    (path / " extra.txt").write_text("带空格文件名\n")
    (path / ".gitignore").write_text("ignored.txt\n")
    (path / "ignored.txt").write_text("不归档的缓存")
    (path / "opencode.json").write_text('{"agent":{"task-config":{}}}')
    index = Path(await git(path, "rev-parse", "--absolute-git-dir")) / "index"
    digest = hashlib.sha256(index.read_bytes()).hexdigest()
    before_head = await git(path, "rev-parse", "HEAD")
    artifact = await capture_workspace_artifact(first, workspace_root=str(project[1]), captured_at=1700000000)
    assert artifact == await capture_workspace_artifact(
        first, workspace_root=str(project[1]), captured_at=1700000000
    )
    assert hashlib.sha256(index.read_bytes()).hexdigest() == digest
    assert await git(path, "rev-parse", "HEAD") == before_head
    second = await prepare(project, "execution-2", base_ref=artifact)
    assert Path(second.directory, "readme.txt").read_text() == "已完成但未提交的工作\n"
    assert Path(second.directory, " extra.txt").read_text() == "带空格文件名\n"
    assert Path(second.directory, "opencode.json").read_text() == '{"agent":{"task-config":{}}}'
    assert not Path(second.directory, "ignored.txt").exists()
    (path / "readme.txt").write_text("试图覆盖已提交产物")
    with pytest.raises(WorkspaceUnsafe, match="不可被修改"):
        await capture_workspace_artifact(first, workspace_root=str(project[1]), captured_at=1700000000)


async def test_artifact_does_not_execute_git_clean_filters_and_enforces_size(project):
    first = await prepare(project)
    path = Path(first.directory)
    (path / ".gitattributes").write_text("*.txt filter=untrusted\n")
    sentinel = project[0] / "must-not-execute"
    await git(path, "config", "filter.untrusted.clean", f"touch {sentinel}")
    await git(path, "config", "filter.untrusted.required", "true")
    artifact = await capture_workspace_artifact(first, workspace_root=str(project[1]), captured_at=1700000000)
    assert artifact and not sentinel.exists()
    with pytest.raises(WorkspaceUnsafe, match="容量"):
        await capture_workspace_artifact(
            first, workspace_root=str(project[1]), captured_at=1700000000, max_bytes=1
        )
