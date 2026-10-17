"""Explicit environment maintenance; OpenCode remains the execution fact source."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import re
import shlex
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update

from app.config.settings import get_settings
from app.database import SessionLocal
from app.domain import EnvironmentStatus, ExecutionMode
from app.gateway.models import GatewayKey, GatewayRoute
from app.gateway.probe import HttpGatewayProbeClient
from app.gateway.runtime import RedisRuntimeStore
from app.gateway.schemas import GatewayKeyCreate
from app.gateway.security import CredentialCipher, gateway_key_digest
from app.gateway.service import GatewayControlService
from app.models import CodeRepository, DigitalEmployee, Event, GitCredential, OpenCodeExecutionEnvironment
from app.runtime.capability import (
    binding_entries,
    binding_names,
    binding_revision,
    discover_names,
    loads_jsonc,
    observe_bindings,
    stored_capability,
    write_capability,
)
from app.runtime.direct_urls import require_direct_url
from app.runtime.environment import ExecutionEnvironmentRuntime
from app.runtime.occupancy import blocking_session_exists, occupying_exists
from app.runtime.opencode_model import route_model_id
from app.runtime.repository import cipher, collect_skill_files

PROVIDER_ID = "astra-gateway"
E2E_MODEL = "opencode/deepseek-v4.1-flash-free"
AGENT_VENV = "/opt/nexus/worker/venv"
WORKER_INSTALL_DIR = "/opt/nexus/worker"
WORKER_SECRET_DIR = "/etc/nexus"
AGENT_PYTHON = f"{AGENT_VENV}/bin/python"


def operation_active(environment: OpenCodeExecutionEnvironment | None) -> bool:
    operation = ((environment.status_detail or {}).get("operation") or {}) if environment else {}
    if operation.get("state") != "RUNNING":
        return False
    try:
        return datetime.fromisoformat(operation["expires_at"]) > datetime.now(UTC)
    except (KeyError, ValueError, TypeError):
        return True


def require_no_operation(environment: OpenCodeExecutionEnvironment | None) -> None:
    if operation_active(environment):
        raise HTTPException(409, "远程环境正在部署或重启，请等待或取消当前操作")


def no_active_operation(now: datetime | None = None):
    """SQL form of operation_active: true when no maintenance reservation is running.

    A missing or unparseable expiry stays reserved. NULL state is not an operation,
    because ``NULL != 'RUNNING'`` is unknown and would reject every idle row.
    """

    current = now or datetime.now(UTC)
    detail = OpenCodeExecutionEnvironment.status_detail
    state = detail["operation"]["state"].as_string()
    expires = detail["operation"]["expires_at"].as_string()
    return or_(
        state.is_(None),
        state != "RUNNING",
        and_(expires.is_not(None), expires <= current.isoformat()),
    )


async def guard_environment_write(session, environment):
    if environment is None:
        return
    await session.refresh(environment)
    require_no_operation(environment)
    # A conditional no-op write takes the row/write lock only until this short
    # transaction commits, including SQLite where SELECT FOR UPDATE is ignored.
    result = await session.execute(
        update(OpenCodeExecutionEnvironment)
        .where(
            OpenCodeExecutionEnvironment.id == environment.id,
            OpenCodeExecutionEnvironment.status_detail == environment.status_detail,
            OpenCodeExecutionEnvironment.status == environment.status,
            no_active_operation(),
        )
        .values(updated_at=OpenCodeExecutionEnvironment.updated_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await session.refresh(environment)
        require_no_operation(environment)
        raise HTTPException(409, "环境状态已变化，请刷新后重试")


async def reserve_operation(employee_id: str, action: str, session):
    settings = get_settings()
    employee = await session.scalar(
        select(DigitalEmployee).where(DigitalEmployee.id == employee_id).with_for_update()
    )
    if not employee:
        raise HTTPException(404, "员工不存在")
    environment = await session.scalar(
        select(OpenCodeExecutionEnvironment)
        .where(OpenCodeExecutionEnvironment.employee_id == employee_id)
        .with_for_update()
    )
    if not environment or environment.mode != ExecutionMode.LINUX_REMOTE:
        raise HTTPException(409, "仅 Linux 远程员工支持部署和重启")
    require_no_operation(environment)
    if not environment.host or not environment.username or not environment.ssh_password:
        raise HTTPException(409, "请先保存远程 IP、用户名和 SSH 密码")
    if not environment.workspace_root.startswith("/"):
        raise HTTPException(409, "工程目录必须是 Linux 绝对路径")
    if action == "deploy" and settings.mcp_transport != "streamable-http":
        raise HTTPException(409, "请先配置 ASTRA_MCP_TRANSPORT=streamable-http 并启动数字图书馆 HTTP 服务")
    occupied = occupying_exists(employee_id)
    active_session = blocking_session_exists(employee_id)
    operation_id = uuid4().hex
    now = datetime.now(UTC)
    operation = {
        "id": operation_id,
        "action": action,
        "state": "RUNNING",
        "started_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=settings.remote_deploy_timeout_seconds + 30)).isoformat(),
    }
    result = await session.execute(
        update(OpenCodeExecutionEnvironment)
        .where(
            OpenCodeExecutionEnvironment.id == environment.id,
            OpenCodeExecutionEnvironment.status_detail == environment.status_detail,
            no_active_operation(now),
            ~occupied,
            ~active_session,
        )
        .values(status=EnvironmentStatus.CHECKING, status_detail={"operation": operation})
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "员工存在占用任务、未结束 Session 或并发环境操作，不能部署或重启")
    await session.commit()
    return environment, operation


def _wheel_digest(data: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return "sha256=" + encoded.decode("ascii")


def agent_wheel() -> tuple[str, bytes]:
    """Worker Agent 代码包。依赖只声明 httpx 与 websockets。"""

    version = "0.4.0"
    dist = f"astra_worker_agent-{version}"
    app_root = Path(__file__).resolve().parents[1]
    names = [
        "app/__init__.py",
        "app/worker_gateway/__init__.py",
        "app/worker_gateway/protocol.py",
        "app/worker_gateway/heartbeat.py",
    ]
    names.extend(
        f"app/worker_agent/{path.name}" for path in sorted((app_root / "worker_agent").glob("*.py"))
    )
    files = [(name, (app_root.parent / name).read_bytes()) for name in names]
    info = f"{dist}.dist-info"
    metadata = (
        "Metadata-Version: 2.1\n"
        "Name: astra-worker-agent\n"
        f"Version: {version}\n"
        "Summary: Nexus Worker Agent\n"
        "Requires-Python: >=3.11\n"
        "Requires-Dist: httpx>=0.27,<1\n"
        "Requires-Dist: websockets>=12\n"
    ).encode()
    wheel_meta = (
        b"Wheel-Version: 1.0\n"
        b"Generator: astra-provision\n"
        b"Root-Is-Purelib: true\n"
        b"Tag: py3-none-any\n"
    )
    files.extend([(f"{info}/METADATA", metadata), (f"{info}/WHEEL", wheel_meta)])
    record = "".join(f"{name},{_wheel_digest(data)},{len(data)}\n" for name, data in files)
    record += f"{info}/RECORD,,\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files:
            archive.writestr(name, data)
        archive.writestr(f"{info}/RECORD", record.encode())
    return f"{dist}-py3-none-any.whl", buffer.getvalue()


def managed_config(
    *,
    config_path,
    model,
    models,
    gateway_url,
    gateway_key,
    mcp_url,
    mcp_key,
    e2e=False,
    skills=None,
    mcp_refs=None,
):
    mcp = {"type": "remote", "url": mcp_url, "enabled": True, "oauth": False}
    if mcp_key:
        mcp["headers"] = {"Authorization": f"Bearer {mcp_key}"}
    provider = None
    if not e2e:
        provider = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Nexus API 中转",
            "options": {"baseURL": gateway_url, "apiKey": gateway_key},
            "models": {name: {"name": name} for name in models},
        }
    return {
        "config_path": config_path,
        "model": E2E_MODEL if e2e else f"{PROVIDER_ID}/{model}",
        "provider": provider,
        "mcp": mcp,
        "mcp_refs": list(mcp_refs or []),
        "skills": list(skills or []),
        "e2e": e2e,
    }


class RemoteProvisioner:
    def __init__(self, environment, operation, *, runtime=None):
        self.environment = environment
        self.operation = operation
        self.settings = get_settings()
        self.runtime = runtime or ExecutionEnvironmentRuntime(self.settings)
        self.steps: list[dict] = []
        self.secrets = [environment.ssh_password, self.settings.mcp_api_key]
        self.ssh = None
        self.new_key_id = None
        self.old_key_id = None
        self.target_model = environment.model_name
        self.target_binary = environment.opencode_path
        self.config_path = None

    def _agent_interpreter(self) -> str:
        configured = (self.settings.remote_python or "").strip()
        return configured or "python3"

    def _gateway_service(self, db, runtime=None):
        return GatewayControlService(
            db,
            cipher=CredentialCipher(self.settings.gateway_master_key),
            probe_client=HttpGatewayProbeClient(self.settings.gateway_probe_timeout_seconds),
            runtime=runtime,
        )

    def redact(self, value):
        text = str(value)
        for secret in self.secrets:
            if secret:
                text = text.replace(secret, "[已隐藏]")
        text = re.sub(r"agw_[A-Za-z0-9_-]+", "[已隐藏]", text)
        text = re.sub(r"Bearer\s+\S+", "Bearer [已隐藏]", text)
        return text[-1500:]

    async def step(self, emit, name, state, detail=""):
        item = {"name": name, "state": state, "passed": state == "passed", "detail": self.redact(detail)}
        self.steps = [s for s in self.steps if s["name"] != name] + [item]
        await emit({"type": "step", **item})

    async def _command(self, command, timeout=30):
        rc, out, err = await asyncio.wait_for(self.ssh.run_command(command), timeout)
        if rc:
            raise RuntimeError(self.redact(err.strip() or out.strip() or f"远程命令退出码 {rc}"))
        return out.strip()

    async def _native_idle(self):
        port = int(self.environment.opencode_server_port)
        query = urlencode({"directory": self.environment.workspace_root})
        url = f"http://127.0.0.1:{port}/session/status?{query}"
        script = (
            "import json,urllib.request\n"
            f"url={json.dumps(url)}\n"
            "try:\n"
            "    print(urllib.request.urlopen(url, timeout=3).read().decode())\n"
            "except Exception:\n"
            "    pass\n"
        )
        out = await self._command(f"python3 -c {shlex.quote(script)} || true")
        if not out:
            return
        try:
            states = json.loads(out)
        except json.JSONDecodeError:
            return
        if isinstance(states, dict) and any(
            isinstance(item, dict) and item.get("type") in {"busy", "retry"} for item in states.values()
        ):
            raise RuntimeError("OpenCode 存在正在执行的 Session，请先停止执行再维护环境")

    async def _gateway_key(self, config_path, models):
        content = await self.ssh.read_file(config_path)
        raw = None
        if content:
            text = content.decode() if isinstance(content, bytes) else content
            try:
                config = loads_jsonc(text)
                raw = config.get("provider", {}).get(PROVIDER_ID, {}).get("options", {}).get("apiKey")
            except (ValueError, AttributeError):
                raise RuntimeError("已有全局配置不是有效 JSON，请人工合并后重试") from None
        async with SessionLocal() as db:
            if raw and isinstance(raw, str):
                key = await db.scalar(
                    select(GatewayKey).where(
                        GatewayKey.key_digest == gateway_key_digest(raw),
                        GatewayKey.owner_id == self.environment.employee_id,
                        GatewayKey.deleted_at.is_(None),
                    )
                )
                if key:
                    self.old_key_id = key.id
                    if (
                        key.enabled
                        and not key.revoked_at
                        and (not key.expires_at or key.expires_at > datetime.now(UTC))
                    ):
                        if not key.allowed_models or set(models).issubset(key.allowed_models):
                            self.secrets.append(raw)
                            return raw
            key, raw = await self._gateway_service(db).create_key(
                GatewayKeyCreate(
                    name=f"数字员工 {self.environment.employee_id}", owner_id=self.environment.employee_id
                ),
                actor="employee-deployment",
                actor_role="admin",
            )
            self.new_key_id = key.id
        self.secrets.append(raw)
        return raw

    async def _install(self, emit):
        await self.step(emit, "部署配置", "running")
        e2e = (self.environment.model_name or "").strip() == E2E_MODEL
        if e2e:
            models: list[str] = []
            selected = E2E_MODEL
        else:
            async with SessionLocal() as db:
                models = list(
                    await db.scalars(
                        select(GatewayRoute.model)
                        .where(GatewayRoute.enabled.is_(True))
                        .order_by(GatewayRoute.model)
                    )
                )
            if not self.settings.gateway_enabled or not models:
                raise RuntimeError("请先在 API 中转配置至少一个启用的模型路由")
            selected = models[0]
            if self.environment.model_name:
                selected = route_model_id(self.environment.model_name)
            if selected not in models:
                raise RuntimeError("员工模型未匹配启用的中转路由，请留空或选择 astra-gateway/<路由模型>")
        home = (await self._command('printf "%s" "$HOME"')).splitlines()[0]
        if not home.startswith("/"):
            raise RuntimeError("无法确定远程用户目录")
        config_path = f"/etc/nexus/opencode/{self.environment.id}/opencode.jsonc"
        self.config_path = config_path
        raw = "" if e2e else await self._gateway_key(config_path, models)
        gateway_url, mcp_url = await self._channel_endpoints()
        self.target_model = E2E_MODEL if e2e else f"{PROVIDER_ID}/{selected}"
        uid = await self._command("id -u")
        if not self.target_binary.startswith("/"):
            self.target_binary = "/usr/local/bin/opencode" if uid == "0" else f"{home}/.local/bin/opencode"
        cache = f"{home}/.cache/nexus-provision"
        await self._command(f"install -d -m 700 {shlex.quote(cache)}")
        stem = f"{cache}/{self.operation['id']}"
        skill_source = Path(self.settings.workspace_root) / "worker-skills"
        payload = managed_config(
            config_path=config_path,
            model=selected,
            models=models,
            gateway_url=gateway_url,
            gateway_key=raw,
            mcp_url=mcp_url,
            mcp_key=self.settings.mcp_api_key,
            e2e=e2e,
            skills=collect_skill_files(list(self.environment.skill_refs or []), skill_source),
            mcp_refs=list(self.environment.mcp_refs or []),
        )
        token_file = ""
        if self.environment.repository_id:
            async with SessionLocal() as db:
                repository = await db.get(CodeRepository, self.environment.repository_id)
                credential = await db.scalar(
                    select(GitCredential).where(GitCredential.repository_id == self.environment.repository_id)
                )
            if repository is None or credential is None:
                raise RuntimeError("绑定的仓库没有凭据")
            token = cipher().decrypt(credential.token_ciphertext)
            self.secrets.append(token)
            token_file = stem + ".token"
            await self.ssh.write_file(token_file, token.encode(), mode=0o600)
            payload["repository"] = {
                "url": repository.url,
                "branch": self.environment.branch or repository.branch,
            }
        jsonc_file = stem + ".jsonc.py"
        await self.ssh.write_file(stem + ".json", json.dumps(payload, ensure_ascii=False).encode())
        await self.ssh.write_file(
            jsonc_file, Path(__file__).resolve().parents[1].joinpath("worker_agent", "jsonc.py").read_bytes()
        )
        await self.ssh.write_file(stem + ".sh", Path(__file__).with_name("remote_install.sh").read_bytes())
        await self.step(emit, "部署配置", "passed", "已准备员工专属中转、数字图书馆与安全连接")
        args = [
            self.environment.workspace_root,
            self.target_binary,
            self.settings.remote_node_version,
            self.settings.remote_opencode_version,
            self.settings.remote_npm_registry,
            stem + ".json",
            self.operation["id"],
            self._agent_interpreter(),
            jsonc_file,
            token_file,
        ]
        command = (
            f"timeout -k 10 {self.settings.remote_deploy_timeout_seconds} bash {shlex.quote(stem + '.sh')} "
            + shlex.join(args)
        )
        channel = await self.ssh.open_exec(command)
        stderr_task = asyncio.create_task(channel.stderr.read())
        tail = ""
        try:
            while line := await channel.stdout.readline():
                text = line.decode(errors="replace").strip()
                if text.startswith("ASTRA_STEP\t"):
                    _, name, state = text.split("\t", 2)
                    await self.step(emit, name, state)
                else:
                    tail = (tail + "\n" + text)[-2000:]
            rc = await channel.wait()
            err = (await stderr_task).decode(errors="replace")
            if rc:
                raise RuntimeError(self.redact(err or tail or f"安装退出码 {rc}"))
        finally:
            await channel.close()
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
            leftovers = [stem + ".sh", stem + ".json", jsonc_file]
            if token_file:
                leftovers.append(token_file)
            await self._command("rm -f " + " ".join(shlex.quote(path) for path in leftovers))

    def _direct_endpoints(self) -> tuple[str, str]:
        return (
            require_direct_url(self.settings.remote_gateway_local_url, "Gateway"),
            require_direct_url(self.settings.mcp_resource_server_url, "图书馆 MCP"),
        )

    async def _channel_endpoints(self) -> tuple[str, str]:
        return self._direct_endpoints()

    async def _restart_via_agent(self, emit):
        await self.step(emit, "重启 OpenCode Serve", "running")
        from app.runtime.worker_client import WorkerOpenCodeClient

        client = WorkerOpenCodeClient(self.settings, environment_id=self.environment.id)
        await client.run_command(
            "restart_opencode",
            {
                "workspace": self.environment.workspace_root,
                "port": self.environment.opencode_server_port,
            },
        )
        health = await client.health()
        await self.step(emit, "重启 OpenCode Serve", "passed", f"健康 · OpenCode {health.get('version')}")

    async def _probe_gateway(self, emit):
        await self.step(emit, "模型中转连接", "running")
        probe = (
            "const fs=require('fs');const c=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
            "const p=c.provider['astra-gateway'];"
            "async function main(){for(let i=0;i<15;i++){"
            "const r=await fetch(p.options.baseURL+'/models',{headers:{Authorization:'Bearer '+"
            "p.options.apiKey},signal:AbortSignal.timeout(5000)});"
            "if(r.ok){const d=await r.json();const id=c.model.slice('astra-gateway/'.length);"
            "if(!d.data?.some(m=>m.id===id))throw Error('中转未提供员工模型');"
            "console.log('模型中转认证与模型路由正常');return;}"
            "if(r.status!==401)throw Error('中转 HTTP '+r.status);"
            "await new Promise(r=>setTimeout(r,2000));}throw Error('中转 Key 未生效');}"
            "main().catch(e=>{console.error(e.message);process.exit(1)})"
        )
        detail = await self._command(
            'export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"; '
            f"node -e {shlex.quote(probe)} {shlex.quote(self.config_path)}",
            timeout=50,
        )
        await self.step(emit, "模型中转连接", "passed", detail)

    async def _install_units(self, emit):
        await self.step(emit, "安装 Worker Agent", "running")
        gateway_url, mcp_url = self._direct_endpoints()
        agent_gateway = require_direct_url(self.settings.worker_agent_gateway_url, "Worker Gateway")
        port = int(self.environment.opencode_server_port)
        opencode_unit = f"nexus-opencode-{self.environment.id}.service"
        worker_unit = f"nexus-worker-{self.environment.id}.service"
        token_path = f"{WORKER_SECRET_DIR}/worker-{self.environment.id}.env"
        opencode_url = f"http://127.0.0.1:{port}"
        timeout = int(self.settings.opencode_control_timeout_seconds)
        opencode_config = self.config_path or f"/etc/nexus/opencode/{self.environment.id}/opencode.jsonc"
        opencode_dir = str(Path(opencode_config).parent)
        opencode_unit_text = (
            "[Unit]\nDescription=Nexus OpenCode\nAfter=network-online.target\n"
            "[Service]\n"
            f"Environment=OPENCODE_CONFIG={opencode_config}\n"
            f"Environment=OPENCODE_CONFIG_DIR={opencode_dir}\n"
            f"ExecStart={self.target_binary} serve --hostname 127.0.0.1 --port {port}\n"
            "Restart=on-failure\n"
            "[Install]\nWantedBy=multi-user.target\n"
        )
        agent_unit_text = (
            "[Unit]\nDescription=Nexus Worker Agent\nAfter=network-online.target\n"
            "[Service]\n"
            f"EnvironmentFile={token_path}\n"
            f"ExecStart={AGENT_PYTHON} -m app.worker_agent\n"
            "Restart=on-failure\n"
            "[Install]\nWantedBy=multi-user.target\n"
        )
        wheel_name, wheel_bytes = agent_wheel()
        wheel_path = f"{WORKER_INSTALL_DIR}/{wheel_name}"
        await self._command(f"install -d -m 755 {WORKER_INSTALL_DIR}")
        await self._command(f"install -d -m 700 {WORKER_SECRET_DIR} /etc/systemd/system")
        await self.ssh.write_file(wheel_path, wheel_bytes, mode=0o644)
        interpreter = shlex.quote(self._agent_interpreter())
        index = (self.settings.remote_pip_index_url or "").strip()
        pip_index = f"-i {shlex.quote(index)} " if index else ""
        pip = (
            f"{AGENT_PYTHON} -m pip install --disable-pip-version-check --upgrade --force-reinstall "
            f"{pip_index}{shlex.quote(wheel_path)}"
        )
        await self._command(
            f"{interpreter} -m venv {AGENT_VENV} && {pip}",
            timeout=300,
        )
        from app.worker_gateway.service import get_gateway

        async with SessionLocal() as session:
            enrolled = await get_gateway().enroll(session, self.environment.id)
        self.secrets.append(enrolled.token)
        env = "\n".join(
            [
                f"ASTRA_WORKER_TOKEN={enrolled.token}",
                f"ASTRA_WORKER_GATEWAY_URL={agent_gateway}",
                f"ASTRA_WORKER_INSTANCE_ID={enrolled.worker_instance_id}",
                f"ASTRA_WORKER_ENVIRONMENT_ID={self.environment.id}",
                f"ASTRA_REMOTE_GATEWAY_URL={gateway_url}",
                f"ASTRA_MCP_RESOURCE_URL={mcp_url}",
                f"ASTRA_WORKER_OPENCODE_URL={opencode_url}",
                f"ASTRA_WORKER_OPENCODE_UNIT={opencode_unit}",
                f"OPENCODE_CONFIG={opencode_config}",
                f"OPENCODE_CONFIG_DIR={opencode_dir}",
                f"ASTRA_WORKER_WORKSPACE_ROOT={self.environment.workspace_root}",
                f"ASTRA_OPENCODE_CONTROL_TIMEOUT_SECONDS={timeout}",
            ]
        ) + "\n"
        await self.ssh.write_file(token_path, env.encode(), mode=0o600)
        await self.ssh.write_file(
            f"/etc/systemd/system/{opencode_unit}", opencode_unit_text.encode(), mode=0o644
        )
        await self.ssh.write_file(
            f"/etc/systemd/system/{worker_unit}",
            agent_unit_text.encode(),
            mode=0o644,
        )
        await self._command(
            "systemctl daemon-reload && "
            f"systemctl enable {shlex.quote(opencode_unit)} {shlex.quote(worker_unit)} && "
            f"systemctl start {shlex.quote(opencode_unit)} && "
            f"systemctl restart {shlex.quote(worker_unit)}"
        )
        await self.step(emit, "安装 Worker Agent", "passed", enrolled.worker_instance_id)

    async def _wait_until_online(self):
        from app.models import WorkerInstance

        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline:
            async with SessionLocal() as session:
                instance = await session.scalar(
                    select(WorkerInstance).where(WorkerInstance.environment_id == self.environment.id)
                )
                if instance is not None and instance.status == "online":
                    return
            await asyncio.sleep(0.2)
        raise RuntimeError("Worker 未上线，通道保持未安装")

    async def _mark_inside_operation(self, emit):
        await self.step(emit, "切换到 Worker", "running")
        await self._wait_until_online()
        from app.runtime.worker_channel import complete_worker_mark

        async def probe():
            await self._probe_mcp(emit)

        async with SessionLocal() as session:
            await complete_worker_mark(
                session,
                self.environment.id,
                self.operation["id"],
                before_write=probe,
            )
        await self.step(emit, "切换到 Worker", "passed", "生效配置与内网地址一致")

    async def _probe_mcp(self, emit):
        await self.step(emit, "图书馆 MCP", "running")
        from app.runtime.worker_client import WorkerOpenCodeClient

        client = WorkerOpenCodeClient(self.settings, environment_id=self.environment.id)
        mcp = await client.request("GET", "/mcp", directory=Path(self.environment.workspace_root))
        if not isinstance(mcp, dict) or mcp.get("nexus-library", {}).get("status") != "connected":
            raise RuntimeError("数字图书馆 MCP 未连接")
        await self.step(emit, "图书馆 MCP", "passed", "数字图书馆已连接")

    async def _restart_offline(self, emit):
        await self.step(emit, "重启 OpenCode Serve", "running")
        unit = f"nexus-opencode-{self.environment.id}.service"
        worker_unit = f"nexus-worker-{self.environment.id}.service"
        await self._command(
            f"systemctl restart {shlex.quote(unit)} {shlex.quote(worker_unit)}"
        )
        await self.step(emit, "重启 OpenCode Serve", "passed", "已通过 SSH 重启单元")

    async def _observe_capability(self) -> dict:
        text = ""
        skill_names: list[str] = []
        error = ""
        try:
            if self.config_path and self.ssh is not None:
                content = await self.ssh.read_file(self.config_path)
                text = content.decode() if isinstance(content, bytes) else (content or "")
                skill_root = str(Path(self.config_path).parent / "skill")
                listing = await self._command(
                    "find "
                    + shlex.quote(skill_root)
                    + " -mindepth 2 -maxdepth 2 -name SKILL.md -printf '%h\\n' || true"
                )
                skill_names = [Path(line.strip()).name for line in listing.splitlines() if line.strip()]
            found = discover_names(skill_names, text)
        except Exception as exc:
            found = set()
            error = self.redact(exc)
        expected = binding_names(self.environment.skill_refs, self.environment.mcp_refs)
        entries = binding_entries(self.environment.skill_refs, self.environment.mcp_refs)
        detail = self.environment.status_detail if isinstance(self.environment.status_detail, dict) else {}
        current = detail.get("capability") if isinstance(detail.get("capability"), dict) else None
        return observe_bindings(
            current,
            desired=binding_revision(entries),
            found=found,
            expected=expected,
            error=error,
            checked_at=datetime.now(UTC).isoformat(),
        )

    async def _finish(self, success, error="", capability=None):
        state = "SUCCEEDED" if success else "FAILED"
        operation = {**self.operation, "state": state, "finished_at": datetime.now(UTC).isoformat()}
        detail = {"operation": operation, "checks": self.steps, "message": self.redact(error)}
        if capability is None:
            capability = stored_capability(self.environment.status_detail)
        if capability is not None:
            detail = write_capability(detail, capability)
        values = {
            "status": EnvironmentStatus.AVAILABLE if success else EnvironmentStatus.UNAVAILABLE,
            "last_checked_at": datetime.now(UTC),
            "status_detail": detail,
        }
        if success:
            values.update(model_name=self.target_model, opencode_path=self.target_binary)
        async with SessionLocal() as db:
            result = await db.execute(
                update(OpenCodeExecutionEnvironment)
                .where(
                    OpenCodeExecutionEnvironment.id == self.environment.id,
                    OpenCodeExecutionEnvironment.status_detail["operation"]["id"].as_string()
                    == self.operation["id"],
                )
                .values(**values)
            )
            if result.rowcount:
                db.add(
                    Event(
                        employee_id=self.environment.employee_id,
                        event_type="ENVIRONMENT_MAINTAINED",
                        phase="environment",
                        message="远程环境维护完成" if success else "远程环境维护未完成",
                        detail={"operation": operation, "checks": self.steps, "error": self.redact(error)},
                    )
                )
            await db.commit()
        applied = result.rowcount == 1
        success = success and applied
        key_to_revoke = (
            self.old_key_id if success and self.new_key_id else self.new_key_id if not success else None
        )
        if key_to_revoke:
            runtime = RedisRuntimeStore(self.settings.redis_url)
            try:
                async with SessionLocal() as db:
                    await self._gateway_service(db, runtime).revoke_key(
                        key_to_revoke, actor="employee-deployment", actor_role="admin"
                    )
            finally:
                await runtime.close()
        return applied

    async def _worker_is_online(self) -> bool:
        from app.models import WorkerInstance

        async with SessionLocal() as session:
            instance = await session.scalar(
                select(WorkerInstance).where(WorkerInstance.environment_id == self.environment.id)
            )
            return instance is not None and instance.status == "online"

    async def run(self, emit):
        success, error = False, ""
        capability = None
        try:
            async with asyncio.timeout(self.settings.remote_deploy_timeout_seconds):
                self._direct_endpoints()
                if self.operation["action"] == "restart" and await self._worker_is_online():
                    await self._restart_via_agent(emit)
                    success = True
                else:
                    await self.step(emit, "SSH 连接与执行检查", "running")
                    self.ssh = await self.runtime.open_session(self.environment)
                    await self._native_idle()
                    await self.step(emit, "SSH 连接与执行检查", "passed")
                    if self.operation["action"] == "deploy":
                        await self._install(emit)
                        await self._probe_gateway(emit)
                        await self._install_units(emit)
                        await self._mark_inside_operation(emit)
                        capability = await self._observe_capability()
                    else:
                        await self._restart_offline(emit)
                    success = True
        except asyncio.CancelledError:
            error = "操作已取消或连接中断；请核对远端状态后重试"
            raise
        except TimeoutError:
            error = "操作超时，远端残留安装受超时及互斥保护；请核对后重试"
        except Exception as exc:
            error = self.redact(exc)
        finally:
            if not success and error:
                current = next(
                    (s["name"] for s in reversed(self.steps) if s["state"] == "running"), "环境维护"
                )
                await self.step(emit, current, "failed", error)
            if self.ssh:
                await self.ssh.close()
                self.ssh = None
            applied = await self._finish(success, error, capability if success else None)
            if not applied:
                success = False
                error = "环境配置或操作记录已变化，旧结果未写入；请刷新后核对"
        await emit(
            {
                "type": "result",
                "success": success,
                "message": ("部署完成" if self.operation["action"] == "deploy" else "重启完成")
                if success
                else error,
                "status": "AVAILABLE" if success else "UNAVAILABLE",
                "checks": self.steps,
            }
        )
