import asyncio
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.config.settings import get_settings
from app.database import SessionLocal, init_database
from app.gateway.models import GatewayKey
from app.gateway.security import gateway_key_digest
from app.main import app
from app.models import DigitalEmployee, OpenCodeExecutionEnvironment, RuntimeSession, Task
from app.runtime.lifecycle import RuntimeService, RuntimeStateError
from app.runtime.remote_provisioning import (
    RemoteProvisioner,
    managed_config,
    operation_active,
    reserve_operation,
)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "assistant_enabled", False)
    monkeypatch.setattr(settings, "mcp_transport", "streamable-http")
    monkeypatch.setattr(settings, "remote_gateway_local_url", "http://10.0.0.8:8110")
    monkeypatch.setattr(settings, "mcp_resource_server_url", "http://10.0.0.8:8201/mcp")
    monkeypatch.setattr(settings, "worker_agent_gateway_url", "ws://10.0.0.8:8100/api/worker-gateway/connect")


async def employee(**overrides):
    await init_database()
    employee_id = "deploy-" + uuid4().hex[:10]
    async with SessionLocal() as db:
        db.add(DigitalEmployee(id=employee_id, name=employee_id, role="build", current_task_count=0))
        await db.flush()
        values = dict(
            employee_id=employee_id,
            mode="LINUX_REMOTE",
            name="Linux",
            host="test.invalid",
            port=22,
            username="root",
            ssh_password="test-ssh-secret",
            workspace_root="/srv/project",
            opencode_path="/usr/local/bin/opencode",
            status="UNKNOWN",
            status_detail={},
        )
        values.update(overrides)
        db.add(OpenCodeExecutionEnvironment(**values))
        await db.commit()
    return employee_id


async def reserve(employee_id):
    async with SessionLocal() as db:
        return await reserve_operation(employee_id, "deploy", db)


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [{"mode": "LOCAL"}, {"ssh_password": None}])
async def test_reservation_rejects_ineligible_environment(overrides):
    employee_id = await employee(**overrides)
    with pytest.raises(HTTPException) as error:
        await reserve(employee_id)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_reservation_checks_runtime_facts_even_when_employee_count_is_zero():
    employee_id = await employee()
    async with SessionLocal() as db:
        task = Task(
            id="task-" + uuid4().hex,
            title="guard",
            task_type="ISSUE",
            category_id="testing-platform",
            employee_id=employee_id,
            status="SUCCEEDED",
        )
        db.add(task)
        await db.flush()
        db.add(
            RuntimeSession(
                id="ses_" + uuid4().hex,
                task_id=task.id,
                employee_id=employee_id,
                status="UNKNOWN",
                workspace="/srv/project",
                environment={},
            )
        )
        await db.commit()
    with pytest.raises(HTTPException) as error:
        await reserve(employee_id)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_reservation_is_exclusive_and_blocks_manual_start():
    employee_id = await employee()
    env, op = await reserve(employee_id)
    with pytest.raises(HTTPException):
        await reserve(employee_id)
    async with SessionLocal() as db:
        task = Task(
            id="task-" + uuid4().hex,
            title="start guard",
            task_type="ISSUE",
            category_id="testing-platform",
            employee_id=employee_id,
            status="PENDING",
        )
        db.add(task)
        await db.commit()
        with pytest.raises(RuntimeStateError, match="部署或重启"):
            await RuntimeService(db).start(task.id)
    await RemoteProvisioner(env, op)._finish(False, "test cleanup")


def test_operation_blocks_configuration_delete_and_test_api():
    employee_id = asyncio.run(employee())
    env, op = asyncio.run(reserve(employee_id))
    with TestClient(app) as client:
        for method, url, body in [
            (
                "put",
                f"/api/employees/{employee_id}/environment",
                {
                    "mode": "LINUX_REMOTE",
                    "name": "Linux",
                    "host": "other.invalid",
                    "username": "root",
                    "workspace_root": "/other",
                },
            ),
            ("post", f"/api/employees/{employee_id}/environment/test", None),
            ("post", f"/api/employees/{employee_id}/environment/restart", None),
            ("delete", f"/api/employees/{employee_id}", None),
        ]:
            response = client.request(method, url, json=body)
            assert response.status_code == 409, response.text
    asyncio.run(RemoteProvisioner(env, op)._finish(False, "test cleanup"))


@pytest.mark.asyncio
async def test_cancel_marks_interruption_and_closes_ssh(monkeypatch):
    employee_id = await employee()
    env, op = await reserve(employee_id)
    entered = asyncio.Event()

    class SSH:
        closed = False

        async def close(self):
            self.closed = True

    ssh = SSH()
    worker = RemoteProvisioner(env, op)

    async def open_session(_environment):
        return ssh

    async def idle():
        return None

    async def install(emit):
        await worker.step(emit, "下载", "running")
        entered.set()
        await asyncio.Event().wait()

    async def emit(_event):
        pass

    monkeypatch.setattr(worker.runtime, "open_session", open_session)
    monkeypatch.setattr(worker, "_native_idle", idle)
    monkeypatch.setattr(worker, "_install", install)
    task = asyncio.create_task(worker.run(emit))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ssh.closed
    async with SessionLocal() as db:
        current = await db.get(OpenCodeExecutionEnvironment, env.id)
        assert current.status == "UNAVAILABLE"
        assert current.status_detail["operation"]["state"] == "FAILED"
        assert not operation_active(current)


@pytest.mark.asyncio
async def test_old_completion_cannot_overwrite_new_operation():
    employee_id = await employee()
    env, op = await reserve(employee_id)
    replacement = {**op, "id": uuid4().hex}
    async with SessionLocal() as db:
        await db.execute(
            update(OpenCodeExecutionEnvironment)
            .where(
                OpenCodeExecutionEnvironment.id == env.id,
            )
            .values(status_detail={"operation": replacement}, model_name="new/model")
        )
        await db.commit()
    assert not await RemoteProvisioner(env, op)._finish(True)
    async with SessionLocal() as db:
        current = await db.get(OpenCodeExecutionEnvironment, env.id)
        assert current.status_detail["operation"]["id"] == replacement["id"]
        assert current.model_name == "new/model"
        assert current.status == "CHECKING"


@pytest.mark.asyncio
async def test_redeploy_reuses_existing_employee_key():
    employee_id = await employee()
    env, op = await reserve(employee_id)
    raw = "agw_existing-test-key"
    async with SessionLocal() as db:
        db.add(
            GatewayKey(
                id="key-" + uuid4().hex,
                name="employee",
                owner_id=employee_id,
                key_prefix=raw[:12],
                key_digest=gateway_key_digest(raw),
                enabled=True,
                allowed_models=["test-model"],
            )
        )
        await db.commit()

    class SSH:
        async def read_file(self, _path):
            return json.dumps({"provider": {"astra-gateway": {"options": {"apiKey": raw}}}}).encode()

    worker = RemoteProvisioner(env, op)
    worker.ssh = SSH()
    assert await worker._gateway_key("/config/opencode.json", ["test-model"]) == raw
    assert worker.new_key_id is None
    assert raw not in worker.redact("request " + raw + " test-ssh-secret Bearer mcp-secret")
    assert "test-ssh-secret" not in worker.redact("test-ssh-secret")
    await worker._finish(False, "test cleanup")


def test_expired_reservation_allows_explicit_retry():
    environment = OpenCodeExecutionEnvironment(
        status_detail={
            "operation": {
                "state": "RUNNING",
                "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            }
        }
    )
    assert not operation_active(environment)


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js required for real config merge")
@pytest.mark.parametrize("jsonc", [False, True])
def test_real_config_merge_preserves_user_settings_and_refuses_jsonc(tmp_path, jsonc):
    target = tmp_path / "opencode.json"
    original = {
        "provider": {"custom": {"options": {"apiKey": "private"}}},
        "mcp": {"custom-mcp": {"enabled": False}},
        "permission": {"bash": "ask"},
    }
    target.write_text(json.dumps(original))
    if jsonc:
        target.with_suffix(".jsonc").write_text("// keep this\n{}")
    payload = managed_config(
        config_path=str(target),
        model="test-model",
        models=["test-model"],
        gateway_url="http://127.0.0.1:8110/v1",
        gateway_key="agw_test",
        mcp_url="http://127.0.0.1:8201/mcp",
        mcp_key="mcp-test",
    )
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps(payload))
    source = Path("app/runtime/remote_install.sh").read_text().split("<<'NODE'\n", 1)[1].split("\nNODE", 1)[0]
    result = subprocess.run(
        [shutil.which("node"), "-", str(payload_file), "op123"], input=source, text=True, capture_output=True
    )
    if jsonc:
        assert result.returncode != 0
        assert json.loads(target.read_text()) == original
        return
    assert result.returncode == 0, result.stderr
    config = json.loads(target.read_text())
    assert config["provider"]["custom"] == original["provider"]["custom"]
    assert config["mcp"]["custom-mcp"] == original["mcp"]["custom-mcp"]
    assert config["permission"] == original["permission"]
    assert config["model"] == "astra-gateway/test-model"
    assert config["mcp"]["nexus-library"]["headers"]["Authorization"] == "Bearer mcp-test"
    assert json.loads((tmp_path / "opencode.json.astra-backup-op123").read_text()) == original
    assert target.stat().st_mode & 0o777 == 0o600


def test_api_streams_progress_and_final_result_without_secrets(monkeypatch):
    employee_id = asyncio.run(employee())

    async def run(self, emit):
        await self.step(emit, "安装", "passed", "完成")
        await self._finish(True)
        await emit({"type": "result", "success": True, "status": "AVAILABLE"})

    monkeypatch.setattr(RemoteProvisioner, "run", run)
    with TestClient(app) as client:
        response = client.post(f"/api/employees/{employee_id}/environment/deploy")
        assert response.status_code == 200
        assert "application/x-ndjson" in response.headers["content-type"]
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[0]["type"] == "step"
        assert events[-1]["success"] is True
        assert "test-ssh-secret" not in response.text
        result = client.get(f"/api/employees/{employee_id}").json()
        assert result["execution_environment"]["status"] == "AVAILABLE"


@pytest.mark.asyncio
async def test_native_busy_refuses_maintenance_before_install():
    env, op = await reserve(await employee())
    worker = RemoteProvisioner(env, op)

    async def run_command(command, timeout=30):
        assert "session/status?directory=%2Fsrv%2Fproject" in command
        return 0, '{"ses_busy": {"type": "busy"}}', ""

    worker.ssh = type("SSH", (), {"run_command": staticmethod(run_command)})()
    with pytest.raises(RuntimeError, match="正在执行"):
        await worker._native_idle()
    await worker._finish(False, "busy")


@pytest.mark.asyncio
async def test_timeout_reports_failure_and_closes_connection(monkeypatch):
    env, op = await reserve(await employee())
    worker = RemoteProvisioner(env, op)
    monkeypatch.setattr(worker.settings, "remote_deploy_timeout_seconds", 0.02)

    class SSH:
        closed = False

        async def close(self):
            self.closed = True

    ssh = SSH()

    async def open_session(_env):
        return ssh

    async def blocked():
        await asyncio.Event().wait()

    monkeypatch.setattr(worker.runtime, "open_session", open_session)
    monkeypatch.setattr(worker, "_native_idle", blocked)
    events = []

    async def emit(event):
        events.append(event)

    await worker.run(emit)
    assert ssh.closed
    assert events[-1]["success"] is False
    assert "超时" in events[-1]["message"]
    async with SessionLocal() as db:
        current = await db.get(OpenCodeExecutionEnvironment, env.id)
        assert current.status_detail["operation"]["state"] == "FAILED"


@pytest.mark.asyncio
async def test_failed_deploy_revokes_only_its_new_key(monkeypatch):
    env, op = await reserve(await employee())
    worker = RemoteProvisioner(env, op)
    worker.new_key_id, worker.old_key_id = "new-key", "old-key"
    revoked = []

    class Service:
        async def revoke_key(self, key_id, **_kwargs):
            revoked.append(key_id)

    monkeypatch.setattr(worker, "_gateway_service", lambda *_args: Service())
    await worker._finish(False, "download failed")
    assert revoked == ["new-key"]


def test_deleted_tunnel_helpers_have_no_callers():
    from pathlib import Path

    root = Path("app")
    banned = (
        "ensure_remote_mcp_tunnel",
        "ensure_remote_gateway_tunnel",
        "close_remote_mcp_tunnels",
        "open_reverse_tunnel",
        "SSHReverseTunnel",
        "SSHTunnel",
    )
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in banned:
            assert name not in text, f"{path} still mentions {name}"


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js required for npm installation metadata")
@pytest.mark.parametrize("outcome", ["success", "install-failed", "wrong-version"])
def test_npm_install_migrates_manual_binary_and_preserves_it_on_failure(tmp_path, outcome):
    import os

    fixture_root = tmp_path / "employee home"
    stub_dir = tmp_path / "tools"
    stub_dir.mkdir()
    target = tmp_path / "opencode"
    target.write_text("#!/bin/sh\nprintf '1.18.35\\n'\n")
    target.chmod(0o755)
    calls = tmp_path / "npm-calls"
    npm = stub_dir / "npm"
    npm.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >>"$npm_calls"
test "$install_outcome" != install-failed || exit 17
prefix="$fixture_root/npm"
mkdir -p "$prefix/bin" "$prefix/lib/node_modules/opencode-ai"
printf '{"version":"1.18.35"}' >"$prefix/lib/node_modules/opencode-ai/package.json"
actual=1.18.35
test "$install_outcome" != wrong-version || actual=1.2.27
printf '#!/bin/sh\\nprintf "%s\\\\n"\\n' "$actual" >"$prefix/bin/opencode"
chmod 755 "$prefix/bin/opencode"
"""
    )
    npm.chmod(0o755)
    script = Path("app/runtime/remote_install.sh").read_text()
    source = script.split("# Keep npm's installation", 1)[1].split("step 'OpenCode 安装' passed", 1)[0]
    source = source[source.index("\n") + 1 :].replace("$HOME/.local/share/astra", "$fixture_root")
    env = dict(os.environ, PATH=str(stub_dir) + os.pathsep + os.environ["PATH"])
    env.update(
        fixture_root=str(fixture_root),
        npm_calls=str(calls),
        binary=str(target),
        opencode_version="1.18.35",
        npm_registry="https://registry.example.invalid",
        install_outcome=outcome,
    )
    result = subprocess.run(["bash", "-eu", "-c", source], env=env, capture_output=True, text=True)
    if outcome != "success":
        assert result.returncode != 0
        assert not target.is_symlink()
        assert "1.18.35" in target.read_text()
        return
    assert result.returncode == 0, result.stderr
    assert target.is_symlink()
    assert "opencode-ai@1.18.35" in calls.read_text()
    assert "--registry https://registry.example.invalid" in calls.read_text()
    assert "--include=optional" in calls.read_text()
    # A satisfied npm package is reused; a matching standalone binary alone was not.
    again = subprocess.run(["bash", "-eu", "-c", source], env=env, capture_output=True, text=True)
    assert again.returncode == 0, again.stderr
    assert len(calls.read_text().splitlines()) == 1
