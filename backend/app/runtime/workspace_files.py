"""Task-scoped filesystem access for uploads and validating native file API requests."""

import asyncio
import os
from pathlib import Path, PurePosixPath
from uuid import uuid4

from app.domain import ExecutionMode
from app.runtime.environment import ExecutionEnvironmentRuntime
from app.runtime.ssh_client import _run_blocking

MAX_UPLOAD = 20 * 1024 * 1024


def relative_path(value: str, workspace: str) -> str:
    path = PurePosixPath(value or ".")
    root = PurePosixPath(workspace)
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError as exc:
            raise PermissionError("路径不属于此任务 Workspace") from exc
    if ".." in path.parts or ".git" in path.parts or "\\" in value or "\x00" in value:
        raise PermissionError("不允许访问此路径")
    return str(path)


async def validate_path(environment, workspace: str, value: str) -> str:
    relative = relative_path(value, workspace)
    if environment.mode == ExecutionMode.LOCAL:
        root = Path(workspace).resolve(strict=True)
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise PermissionError("符号链接指向任务 Workspace 之外")
    else:
        ssh = await ExecutionEnvironmentRuntime().open_session(environment)
        try:

            def validate():
                with ssh._client.open_sftp() as sftp:
                    root = sftp.normalize(workspace)
                    target = sftp.normalize(f"{workspace}/{relative}")
                    if target != root and not target.startswith(root.rstrip("/") + "/"):
                        raise PermissionError("符号链接指向任务 Workspace 之外")

            await _run_blocking(validate)
        finally:
            await ssh.close()
    return relative


async def upload(environment, workspace: str, filename: str, content: bytes) -> str:
    if not filename or filename != PurePosixPath(filename).name or "\\" in filename:
        raise ValueError("文件名无效")
    if len(content) > MAX_UPLOAD:
        raise ValueError("文件不能超过 20 MB")
    relative = f"uploads/{uuid4().hex[:12]}-{filename}"
    if environment.mode == ExecutionMode.LOCAL:
        root = Path(workspace).resolve(strict=True)
        folder = root / "uploads"
        folder.mkdir(exist_ok=True)
        if folder.is_symlink() or not folder.resolve().is_relative_to(root):
            raise PermissionError("上传目录越界")

        def write():
            # O_NOFOLLOW blocks a swapped target symlink; dir_fd anchors the opened upload directory.
            directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                fd = os.open(
                    Path(relative).name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
                with os.fdopen(fd, "wb") as stream:
                    stream.write(content)
            finally:
                os.close(directory)

        await asyncio.to_thread(write)
    else:
        ssh = await ExecutionEnvironmentRuntime().open_session(environment)
        try:

            def write():
                with ssh._client.open_sftp() as sftp:
                    root = sftp.normalize(workspace)
                    folder = f"{root}/uploads"
                    try:
                        sftp.mkdir(folder)
                    except OSError:
                        pass
                    if sftp.normalize(folder) != folder:
                        raise PermissionError("上传目录越界")
                    with sftp.open(f"{root}/{relative}", "wx") as stream:
                        stream.write(content)

            await _run_blocking(write)
        finally:
            await ssh.close()
    return f"{workspace}/{relative}"
