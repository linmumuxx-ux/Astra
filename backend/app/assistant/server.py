"""平台助手专用 OpenCode Server 生命周期。

该进程始终在 ``nexus-assistant`` 工作区内启动，并把当前 Python
虚拟环境的可执行目录注入 PATH，使 OpenCode 在 macOS、Linux 和
Windows 上都能找到 ``astra-assistant-mcp`` 入口。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx

from app.config.settings import Settings, get_settings
from app.executors.process import local_command
from app.runtime.opencode_server import OpenCodeServerManager


class AssistantOpenCodeServerManager(OpenCodeServerManager):
    """Describe, start and probe the isolated platform-assistant server."""

    def __init__(self, settings: Settings | None = None, *, binary: str | None = None):
        super().__init__(settings, binary=binary)

    @property
    def base_url(self) -> str:
        return self.settings.resolved_assistant_opencode_url

    @property
    def workspace(self) -> Path:
        return self.settings.resolved_assistant_workspace

    @property
    def executable_directory(self) -> Path:
        """Return the active environment's scripts directory without resolving venv links."""

        return Path(sys.executable).parent

    @property
    def mcp_entrypoint(self) -> Path:
        name = "astra-assistant-mcp.exe" if os.name == "nt" else "astra-assistant-mcp"
        return self.executable_directory / name

    def command(self) -> list[str]:
        return local_command(
            self.binary,
            [
                "serve",
                "--hostname",
                self.settings.assistant_opencode_hostname,
                "--port",
                str(self.settings.assistant_opencode_port),
            ],
        )

    def process_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        # ``sys.executable`` is commonly a symlink inside Unix virtualenvs.
        # Resolving it points at the base Python installation, where the MCP
        # console script does not exist. Keep the virtualenv's own bin/Scripts
        # directory at the front of PATH on every platform.
        executable_dir = str(self.executable_directory)
        current_path = environment.get("PATH", "")
        environment["PATH"] = os.pathsep.join(item for item in (executable_dir, current_path) if item)
        environment["OPENCODE_SERVER_USERNAME"] = self.settings.assistant_opencode_username
        if self.settings.assistant_opencode_password:
            environment["OPENCODE_SERVER_PASSWORD"] = self.settings.assistant_opencode_password
        else:
            # Do not accidentally reuse credentials intended for the execution server.
            environment.pop("OPENCODE_SERVER_PASSWORD", None)
        return environment

    @property
    def auth(self) -> httpx.BasicAuth | None:
        if not self.settings.assistant_opencode_password:
            return None
        return httpx.BasicAuth(
            self.settings.assistant_opencode_username,
            self.settings.assistant_opencode_password,
        )


def main() -> int:
    manager = AssistantOpenCodeServerManager(get_settings())
    if not manager.settings.assistant_enabled:
        return 0
    if manager.settings.assistant_opencode_url:
        print(
            "ASTRA_ASSISTANT_OPENCODE_URL 已配置，不启动本地助手 OpenCode Server。",
            file=sys.stderr,
        )
        return 0
    if not manager.workspace.is_dir():
        print(f"助手工作区不存在：{manager.workspace}", file=sys.stderr)
        return 1

    command = manager.command()
    environment = manager.process_environment()
    os.chdir(manager.workspace)
    if os.name != "nt":
        os.execvpe(command[0], command, environment)
    process = subprocess.run(command, env=environment, check=False)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
