import asyncio
import shlex
from dataclasses import dataclass
from uuid import uuid4

from app.config.settings import Settings, get_settings
from app.domain import EnvironmentStatus, ExecutionMode
from app.executors.process import (
    local_command,
    process_group_options,
    resolve_executable,
)
from app.models import OpenCodeExecutionEnvironment
from app.runtime.ssh_client import SSHSession


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
        "has_ssh_password": environment.has_ssh_password,
        "opencode_server_port": environment.opencode_server_port,
        "opencode_path": environment.opencode_path,
        "model_name": environment.model_name,
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
        ssh_password=None,
        opencode_server_port=snapshot.get("opencode_server_port", 4096),
        opencode_path=snapshot["opencode_path"],
        model_name=snapshot.get("model_name"),
        workspace_root=snapshot["workspace_root"],
        labels=snapshot.get("labels", []),
        status=EnvironmentStatus.AVAILABLE,
    )


class ExecutionEnvironmentRuntime:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    async def open_session(self, environment: OpenCodeExecutionEnvironment) -> SSHSession:
        if not environment.host or not environment.username:
            raise RuntimeError("Linux 远程环境缺少 Host 或 Username")
        if not environment.ssh_password:
            raise RuntimeError("Linux 远程环境尚未配置 SSH 密码")
        session = SSHSession(
            host=environment.host,
            port=environment.port,
            username=environment.username,
            password=environment.ssh_password,
            connect_timeout=self.settings.ssh_connect_timeout_seconds,
        )
        await session.connect()
        return session

    async def run_remote(
        self,
        environment: OpenCodeExecutionEnvironment,
        command: str,
        *,
        timeout: int | None = None,
    ) -> tuple[int, str, str]:
        session: SSHSession | None = None
        try:
            session = await self.open_session(environment)
            return await asyncio.wait_for(
                session.run_command(command),
                timeout=timeout or self.settings.opencode_timeout_seconds,
            )
        except TimeoutError:
            return 124, "", "远程命令执行超时"
        except Exception as exc:
            return 255, "", str(exc)
        finally:
            if session:
                await session.close()

    async def test(self, environment: OpenCodeExecutionEnvironment) -> list[CheckItem]:
        if environment.mode == ExecutionMode.LOCAL:
            return await self._test_local(environment)
        return await self._test_remote(environment)

    async def _test_local(self, environment: OpenCodeExecutionEnvironment) -> list[CheckItem]:
        binary = environment.opencode_path
        resolved = resolve_executable(binary)
        exists = bool(resolved)
        checks = [
            CheckItem(
                "Agent 命令存在",
                exists,
                f"已找到 {resolved}" if exists else f"未找到 {binary}",
            )
        ]
        if exists:
            try:
                process = await asyncio.create_subprocess_exec(
                    *local_command(str(resolved), ["--version"]),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    **process_group_options(),
                )
                output, _ = await asyncio.wait_for(process.communicate(), timeout=15)
                started = process.returncode == 0
                detail = output.decode("utf-8", errors="replace").strip() or "命令执行完成"
            except (OSError, TimeoutError) as exc:
                started, detail = False, str(exc)
            checks.append(CheckItem("Agent 命令可启动", started, detail[:500]))
        else:
            checks.append(CheckItem("Agent 命令可启动", False, "未执行：Agent 命令不存在"))

        root = self.settings.employee_workspace_path(environment.workspace_root)
        try:
            if not root.is_dir():
                raise FileNotFoundError(f"Workspace 不存在：{root}")
            probe = root / f".astra-write-check-{uuid4().hex}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            workspace_ok, workspace_detail = True, f"可写：{root.resolve()}"
        except OSError as exc:
            workspace_ok, workspace_detail = False, str(exc)
        checks.append(CheckItem("Workspace 可用", workspace_ok, workspace_detail))
        if self.settings.executor_type == "opencode_server":
            from app.executors.opencode_server import OpenCodeServerClient

            port = environment.opencode_server_port
            if port in {self.settings.opencode_server_port, self.settings.assistant_opencode_port}:
                checks.append(
                    CheckItem("OpenCode Server", False, "端口与平台公共/助手 Serve 冲突，请配置独立端口")
                )
            else:
                client = OpenCodeServerClient(self.settings, base_url=f"http://127.0.0.1:{port}")
                try:
                    health = await client.health()
                    checks.append(
                        CheckItem("OpenCode Server", True, f"健康：{port} · {health.get('version')}")
                    )
                except Exception as exc:
                    import socket

                    with socket.socket() as probe:
                        probe.settimeout(1)
                        occupied = probe.connect_ex(("127.0.0.1", port)) == 0
                    checks.append(
                        CheckItem(
                            "OpenCode Server",
                            not occupied,
                            f"端口冲突或 Serve 异常：{exc}" if occupied else "未启动；任务执行时将自动启动",
                        )
                    )
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
                    CheckItem("Agent 命令存在", False, "未执行：SSH 连接失败"),
                    CheckItem("Agent 命令可启动", False, "未执行：SSH 连接失败"),
                ]
            )
            return checks

        root = shlex.quote(environment.workspace_root)
        code, _, stderr = await self.run_remote(
            environment, f"test -d {root} && test -w {root}", timeout=20
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
                "Agent 命令存在",
                code == 0,
                f"已找到 {environment.opencode_path}"
                if code == 0
                else (stderr.strip() or "远程 Agent 命令不存在"),
            )
        )
        if code == 0:
            code, stdout, stderr = await self.run_remote(environment, f"{binary} --version", timeout=20)
            detail = stdout.strip() or stderr.strip() or f"退出码 {code}"
            checks.append(CheckItem("Agent 命令可启动", code == 0, detail[:500]))
        else:
            checks.append(CheckItem("Agent 命令可启动", False, "未执行：Agent 命令不存在"))
        if code == 0 and self.settings.executor_type == "opencode_server":
            from app.executors.opencode_remote_server import test_remote_server

            server_ok, server_detail = await test_remote_server(environment, self.settings, self)
            checks.append(CheckItem("OpenCode Server", server_ok, server_detail[:500]))
        elif self.settings.executor_type == "opencode_server":
            checks.append(CheckItem("OpenCode Server", False, "未执行：Agent 命令不可启动"))
        return checks


def checks_status(checks: list[CheckItem]) -> EnvironmentStatus:
    return (
        EnvironmentStatus.AVAILABLE
        if checks and all(item.passed for item in checks)
        else EnvironmentStatus.UNAVAILABLE
    )
