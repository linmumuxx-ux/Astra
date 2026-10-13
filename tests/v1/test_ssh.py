"""真实本机 SSH 握手校验；未知或变化的主机密钥不能收到认证秘密。"""

import socket
import threading

import paramiko
import pytest

from domains.runtime.ssh import SSHSession


@pytest.mark.asyncio
@pytest.mark.parametrize("pin", ["valid", "unknown", "changed"])
async def test_ssh_pinned_host_before_password_authentication(tmp_path, pin):
    host_key = paramiko.RSAKey.generate(2048)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)
    port = listener.getsockname()[1]
    authenticated = threading.Event()
    stop = threading.Event()
    errors = []

    class Server(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            authenticated.set()
            return paramiko.AUTH_SUCCESSFUL

    def serve():
        transport = None
        try:
            connection, _ = listener.accept()
            transport = paramiko.Transport(connection)
            transport.add_server_key(host_key)
            transport.start_server(server=Server())
            stop.wait(5)
        except (EOFError, paramiko.SSHException):
            pass  # 未知主机客户端主动终止握手。
        except Exception as exc:
            errors.append(type(exc).__name__)
        finally:
            if transport:
                transport.close()
            listener.close()

    hosts = paramiko.HostKeys()
    if pin != "unknown":
        key = host_key if pin == "valid" else paramiko.RSAKey.generate(2048)
        hosts.add(f"[127.0.0.1]:{port}", key.get_name(), key)
    file = tmp_path / "known_hosts"
    hosts.save(str(file))
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    client = SSHSession(
        host="127.0.0.1",
        port=port,
        username="test",
        password="test-only",
        known_hosts=str(file),
        connect_timeout=3,
    )
    try:
        if pin == "valid":
            await client.connect()
            assert authenticated.is_set() and client.is_active()
        else:
            with pytest.raises(paramiko.SSHException):
                await client.connect()
            assert not authenticated.is_set()
    finally:
        await client.close()
        stop.set()
        thread.join(5)
    assert not thread.is_alive() and not errors
