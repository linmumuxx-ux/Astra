import asyncio
import select
import socketserver
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import paramiko

_SSH_THREADS = ThreadPoolExecutor(max_workers=8, thread_name_prefix="astra-ssh")


async def _run_blocking(function, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_SSH_THREADS, function, *args)


class _AsyncStream:
    """Expose a Paramiko channel file through the async reader methods we use."""

    def __init__(self, stream: Any):
        self._stream = stream

    async def readline(self) -> bytes:
        return await _run_blocking(self._stream.readline)

    async def read(self, size: int = -1) -> bytes:
        return await _run_blocking(self._stream.read, size)

    async def close(self) -> None:
        await _run_blocking(self._stream.close)


class RemoteExecChannel:
    """Small asyncio-Process-compatible facade for a Paramiko exec channel."""

    def __init__(self, channel: Any):
        self._channel = channel
        self.stdout = _AsyncStream(channel.makefile("rb", -1))
        self.stderr = _AsyncStream(channel.makefile_stderr("rb", -1))
        self._returncode: int | None = None

    @property
    def returncode(self) -> int | None:
        return self._returncode

    async def wait(self) -> int:
        if self._returncode is None:
            self._returncode = await _run_blocking(self._channel.recv_exit_status)
        return self._returncode

    async def terminate(self) -> None:
        if not self._channel.closed:
            await _run_blocking(self._channel.close)
        if self._returncode is None:
            self._returncode = -15

    async def close(self) -> None:
        await self.terminate()


class _ForwardServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _ForwardHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server = self.server
        try:
            channel = server.transport.open_channel(  # type: ignore[attr-defined]
                "direct-tcpip",
                server.remote_address,  # type: ignore[attr-defined]
                self.request.getpeername(),
            )
        except Exception:
            return
        try:
            while True:
                readable, _, _ = select.select([self.request, channel], [], [])
                if self.request in readable:
                    payload = self.request.recv(65536)
                    if not payload:
                        break
                    channel.sendall(payload)
                if channel in readable:
                    payload = channel.recv(65536)
                    if not payload:
                        break
                    self.request.sendall(payload)
        except (EOFError, OSError):
            pass
        finally:
            channel.close()


class SSHTunnel:
    """Local loopback TCP endpoint forwarded through one Paramiko transport."""

    def __init__(self, server: _ForwardServer, thread: threading.Thread):
        self._server = server
        self._thread = thread
        self._closed = False

    @property
    def local_port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.local_port}"

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        def stop() -> None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5)

        await _run_blocking(stop)


class SSHSession:
    """One password-authenticated Paramiko connection used for remote execution."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        connect_timeout: int = 10,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.connect_timeout = connect_timeout
        self._client = paramiko.SSHClient()
        self._client.load_system_host_keys()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    async def connect(self) -> None:
        await _run_blocking(
            lambda: self._client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=self.connect_timeout,
                banner_timeout=self.connect_timeout,
                auth_timeout=self.connect_timeout,
                allow_agent=False,
                look_for_keys=False,
            )
        )
        transport = self._client.get_transport()
        if transport is not None:
            transport.set_keepalive(30)

    async def open_tunnel(
        self,
        *,
        remote_host: str = "127.0.0.1",
        remote_port: int,
    ) -> SSHTunnel:
        def start() -> SSHTunnel:
            transport = self._client.get_transport()
            if transport is None or not transport.is_active():
                raise RuntimeError("SSH 连接未建立或已断开")
            server = _ForwardServer(("127.0.0.1", 0), _ForwardHandler)
            server.transport = transport  # type: ignore[attr-defined]
            server.remote_address = (remote_host, remote_port)  # type: ignore[attr-defined]
            thread = threading.Thread(
                target=server.serve_forever,
                name=f"astra-ssh-tunnel-{self.host}-{remote_port}",
                daemon=True,
            )
            thread.start()
            return SSHTunnel(server, thread)

        return await _run_blocking(start)

    async def open_exec(self, command: str) -> RemoteExecChannel:
        def open_channel():
            transport = self._client.get_transport()
            if transport is None or not transport.is_active():
                raise RuntimeError("SSH 连接未建立或已断开")
            channel = transport.open_session(timeout=self.connect_timeout)
            channel.exec_command(command)
            # Remote wrappers must never wait for interactive stdin.
            channel.shutdown_write()
            return channel

        return RemoteExecChannel(await _run_blocking(open_channel))

    async def run_command(self, command: str) -> tuple[int, str, str]:
        channel = await self.open_exec(command)
        try:
            stdout, stderr, exit_code = await asyncio.gather(
                channel.stdout.read(),
                channel.stderr.read(),
                channel.wait(),
            )
            return (
                exit_code,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        finally:
            await channel.close()

    async def close(self) -> None:
        await _run_blocking(self._client.close)
