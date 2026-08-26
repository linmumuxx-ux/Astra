import asyncio
import os
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import uuid4

from app.config.settings import Settings, get_settings
from app.domain import EnvironmentStatus, ExecutionMode
from app.models import OpenCodeExecutionEnvironment, Task


@dataclass(slots=True)
class CheckItem:
    name: str
    passed: bool
    detail: str


def environment_snapshot(environment: OpenCodeExecutionEnvironment) -> dict:
    return {
        "environment_id": environment.id,
        "mode": environment.mode,
        "name": environment.name,
        "host": environment.host,
        "port": environment.port,
        "username": environment.username,
        "auth_method": environment.auth_method,
        "ssh_key_path": environment.ssh_key_path,
        "opencode_path": environment.opencode_path,
        "workspace_root": environment.workspace_root,
        "labels": list(environment.labels or []),
    }


def environment_from_snapshot(snapshot: dict, employee_id: str) -> OpenCodeExecutionEnvironment:
    return OpenCodeExecutionEnvironment(
        id=snapshot.get("environment_id"),
        employee_id=employee_id,
        mode=snapshot["mode"],
        name=snapshot["name"],
        host=snapshot.get("host"),
        port=snapshot.get("port", 22),
        username=snapshot.get("username"),
        auth_method=snapshot.get("auth_method", "SSH_AGENT"),
        ssh_key_path=snapshot.get("ssh_key_path"),
        opencode_path=snapshot["opencode_path"],
        workspace_root=snapshot["workspace_root"],
        labels=snapshot.get("labels", []),
        status=EnvironmentStatus.AVAILABLE,
    )


class ExecutionEnvironmentRuntime:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def ssh_prefix(self, environment: OpenCodeExecutionEnvironment) -> list[str]:
        command = [
            self.settings.ssh_binary,
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={self.settings.ssh_connect_timeout_seconds}",
            "-p",
            str(environment.port),
        ]
        if environment.auth_method == "SSH_KEY" and environment.ssh_key_path:
            command.extend(["-i", environment.ssh_key_path])
        command.append(f"{environment.username}@{environment.host}")
        return command

    async def run_remote(
        self,
        environment: OpenCodeExecutionEnvironment,
        command: str,
        *,
        timeout: int | None = None,
    ) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *self.ssh_prefix(environment),
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout or self.settings.opencode_timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return 124, "", "远程命令执行超时"
        return (
            process.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def test(self, environment: OpenCodeExecutionEnvironment) -> list[CheckItem]:
        if environment.mode == ExecutionMode.LOCAL:
            return await self._test_local(environment)
        return await self._test_remote(environment)

    async def _test_local(self, environment: OpenCodeExecutionEnvironment) -> list[CheckItem]:
        binary = environment.opencode_path
        resolved = shutil.which(binary) if os.sep not in binary else binary
        exists = bool(resolved and Path(resolved).expanduser().is_file())
        checks = [
            CheckItem(
                "OpenCode 存在",
                exists,
                f"已找到 {resolved}" if exists else f"未找到 {binary}",
            )
        ]
        if exists:
            try:
                process = await asyncio.create_subprocess_exec(
                    str(resolved),
                    "--version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                output, _ = await asyncio.wait_for(process.communicate(), timeout=15)
                started = process.returncode == 0
                detail = output.decode("utf-8", errors="replace").strip() or "命令执行完成"
            except (OSError, TimeoutError) as exc:
                started, detail = False, str(exc)
            checks.append(CheckItem("OpenCode 可启动", started, detail[:500]))
        else:
            checks.append(CheckItem("OpenCode 可启动", False, "未执行：OpenCode 不存在"))

        root = Path(environment.workspace_root).expanduser()
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / f".astra-write-check-{uuid4().hex}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            workspace_ok, workspace_detail = True, f"可写：{root.resolve()}"
        except OSError as exc:
            workspace_ok, workspace_detail = False, str(exc)
        checks.append(CheckItem("Workspace 可用", workspace_ok, workspace_detail))
        return checks

    async def _test_remote(self, environment: OpenCodeExecutionEnvironment) -> list[CheckItem]:
        code, stdout, stderr = await self.run_remote(environment, "true", timeout=20)
        connected = code == 0
        checks = [
            CheckItem(
                "SSH 连接",
                connected,
                "连接成功" if connected else (stderr.strip() or stdout.strip() or f"退出码 {code}"),
            )
        ]
        if not connected:
            checks.extend(
                [
                    CheckItem("Workspace 可用", False, "未执行：SSH 连接失败"),
                    CheckItem("OpenCode 存在", False, "未执行：SSH 连接失败"),
                    CheckItem("OpenCode 可启动", False, "未执行：SSH 连接失败"),
                ]
            )
            return checks

        root = shlex.quote(environment.workspace_root)
        code, _, stderr = await self.run_remote(
            environment, f"mkdir -p {root} && test -d {root} && test -w {root}", timeout=20
        )
        checks.append(
            CheckItem(
                "Workspace 可用",
                code == 0,
                f"可写：{environment.workspace_root}" if code == 0 else (stderr.strip() or f"退出码 {code}"),
            )
        )
        binary = shlex.quote(environment.opencode_path)
        exists_command = (
            f"test -x {binary}" if "/" in environment.opencode_path else f"command -v {binary} >/dev/null"
        )
        code, _, stderr = await self.run_remote(environment, exists_command, timeout=20)
        checks.append(
            CheckItem(
                "OpenCode 存在",
                code == 0,
                f"已找到 {environment.opencode_path}"
                if code == 0
                else (stderr.strip() or "远程 OpenCode 不存在"),
            )
        )
        if code == 0:
            code, stdout, stderr = await self.run_remote(environment, f"{binary} --version", timeout=20)
            detail = stdout.strip() or stderr.strip() or f"退出码 {code}"
            checks.append(CheckItem("OpenCode 可启动", code == 0, detail[:500]))
        else:
            checks.append(CheckItem("OpenCode 可启动", False, "未执行：OpenCode 不存在"))
        return checks

    async def prepare_remote_workspace(self, task: Task, environment: OpenCodeExecutionEnvironment) -> Path:
        workspace = PurePosixPath(environment.workspace_root) / task.id
        directories = " ".join(
            shlex.quote(str(workspace / name)) for name in ("source", "output", "evidence", "logs", "meta")
        )
        commands = [f"mkdir -p {directories}"]
        project_path = task.input.get("project_path")
        if project_path:
            project = shlex.quote(str(project_path))
            source = shlex.quote(str(workspace / "source"))
            commands.append(
                f'test -d {project} && if [ -z "$(ls -A {source})" ]; then cp -a {project}/. {source}/; fi'
            )
        code, _, stderr = await self.run_remote(environment, " && ".join(commands), timeout=120)
        if code:
            raise RuntimeError(f"远程 Workspace 创建失败: {stderr.strip() or f'退出码 {code}'}")
        return Path(str(workspace))


def checks_status(checks: list[CheckItem]) -> EnvironmentStatus:
    return (
        EnvironmentStatus.AVAILABLE
        if checks and all(item.passed for item in checks)
        else EnvironmentStatus.UNAVAILABLE
    )
