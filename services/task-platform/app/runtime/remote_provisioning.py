"""Explicit environment maintenance; OpenCode remains the execution fact source."""

from __future__ import annotations

import asyncio
import json
import re
import shlex
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update

from app.config.settings import get_settings
from app.database import SessionLocal
from app.domain import EnvironmentStatus, ExecutionMode
from app.executors.opencode_remote_server import (
    RemoteOpenCodeServerConnection,
    ensure_remote_gateway_tunnel,
    ensure_remote_mcp_tunnel,
)
from app.executors.opencode_server import OpenCodeServerClient, OpenCodeServerUnavailable
from app.gateway.models import GatewayKey, GatewayRoute
from app.gateway.probe import HttpGatewayProbeClient
from app.gateway.runtime import RedisRuntimeStore
from app.gateway.schemas import GatewayKeyCreate
from app.gateway.security import CredentialCipher, gateway_key_digest
from app.gateway.service import GatewayControlService
from app.models import DigitalEmployee, Event, OpenCodeExecutionEnvironment
from app.runtime.environment import ExecutionEnvironmentRuntime
from app.runtime.occupancy import blocking_session_exists, occupying_exists
from app.runtime.opencode_model import route_model_id

PROVIDER_ID = "astra-gateway"


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


async def guard_environment_write(session, environment):
    require_no_operation(environment)
    if environment is None:
        return
    # A conditional no-op write takes the row/write lock only until this short
    # transaction commits, including SQLite where SELECT FOR UPDATE is ignored.
    result = await session.execute(
        update(OpenCodeExecutionEnvironment)
        .where(
            OpenCodeExecutionEnvironment.id == environment.id,
            OpenCodeExecutionEnvironment.status_detail == environment.status_detail,
            OpenCodeExecutionEnvironment.status == environment.status,
        )
        .values(updated_at=OpenCodeExecutionEnvironment.updated_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
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


def managed_config(*, config_path, model, models, gateway_url, gateway_key, mcp_url, mcp_key):
    mcp = {"type": "remote", "url": mcp_url, "enabled": True, "oauth": False}
    if mcp_key:
        mcp["headers"] = {"Authorization": f"Bearer {mcp_key}"}
    return {
        "config_path": config_path,
        "model": f"{PROVIDER_ID}/{model}",
        "provider": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Astra API 中转",
            "options": {"baseURL": gateway_url, "apiKey": gateway_key},
            "models": {name: {"name": name} for name in models},
        },
        "mcp": mcp,
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
        tunnel = await self.ssh.open_tunnel(
            remote_host="127.0.0.1",
            remote_port=self.environment.opencode_server_port,
        )
        try:
            client = OpenCodeServerClient(self.settings, base_url=tunnel.base_url)
            try:
                await client.health()
            except OpenCodeServerUnavailable:
                return
            states = await client.request(
                "GET", "/session/status", directory=Path(self.environment.workspace_root)
            )
            if any(s.get("type") in {"busy", "retry"} for s in states.values()):
                raise RuntimeError("OpenCode 存在正在执行的 Session，请先停止执行再维护环境")
        finally:
            await tunnel.close()

    async def _gateway_key(self, config_path, models):
        content = await self.ssh.read_file(config_path)
        raw = None
        if content:
            try:
                config = json.loads(content)
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
        selected = route_model_id(self.environment.model_name) if self.environment.model_name else models[0]
        if selected not in models:
            raise RuntimeError("员工模型未匹配启用的中转路由，请留空或选择 astra-gateway/<路由模型>")
        paths = (
            await self._command('printf "%s\\n%s\\n" "$HOME" "${XDG_CONFIG_HOME:-$HOME/.config}"')
        ).splitlines()
        if len(paths) != 2 or any(not p.startswith("/") for p in paths):
            raise RuntimeError("无法确定远程用户全局配置目录")
        home, config_home = paths
        config_path = f"{config_home}/opencode/opencode.json"
        self.config_path = config_path
        if await self.ssh.read_file(config_path + "c") is not None:
            raise RuntimeError("已有全局 opencode.jsonc，请人工合并后重试，未覆盖配置")
        raw = await self._gateway_key(config_path, models)
        gateway_url = await ensure_remote_gateway_tunnel(self.environment, self.settings, self.runtime)
        mcp_url = await ensure_remote_mcp_tunnel(self.environment, self.settings, self.runtime)
        self.target_model = f"{PROVIDER_ID}/{selected}"
        uid = await self._command("id -u")
        if not self.target_binary.startswith("/"):
            self.target_binary = "/usr/local/bin/opencode" if uid == "0" else f"{home}/.local/bin/opencode"
        cache = f"{home}/.cache/astra-provision"
        await self._command(f"install -d -m 700 {shlex.quote(cache)}")
        stem = f"{cache}/{self.operation['id']}"
        payload = managed_config(
            config_path=config_path,
            model=selected,
            models=models,
            gateway_url=gateway_url,
            gateway_key=raw,
            mcp_url=mcp_url,
            mcp_key=self.settings.mcp_api_key,
        )
        await self.ssh.write_file(stem + ".json", json.dumps(payload, ensure_ascii=False).encode())
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
            await self._command(f"rm -f {shlex.quote(stem + '.sh')} {shlex.quote(stem + '.json')}")

    async def _restart(self, emit):
        await self.step(emit, "重启 OpenCode Serve", "running")
        # Use the existing PID/cwd/port ownership checks, never kill by process name.
        self.environment.opencode_path = self.target_binary
        self.environment.model_name = self.target_model
        connection = RemoteOpenCodeServerConnection(self.environment, self.settings, self.runtime)
        await connection._require_workspace_config(self.ssh)
        if (self.target_model or "").startswith(f"{PROVIDER_ID}/"):
            await ensure_remote_gateway_tunnel(self.environment, self.settings, self.runtime)
        await ensure_remote_mcp_tunnel(self.environment, self.settings, self.runtime)
        tunnel = await self.ssh.open_tunnel(
            remote_host="127.0.0.1", remote_port=self.environment.opencode_server_port
        )
        try:
            client = OpenCodeServerClient(self.settings, base_url=tunnel.base_url)
            await connection._start_server(self.ssh)
            connection.session = self.ssh
            await connection._wait_until_ready(client)
            health = await client.health()
            await self.step(emit, "重启 OpenCode Serve", "passed", f"健康 · OpenCode {health.get('version')}")
            if self.operation["action"] == "deploy":
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
                await self.step(emit, "图书馆 MCP", "running")
                mcp = await client.request("GET", "/mcp", directory=Path(self.environment.workspace_root))
                if mcp.get("nexus-library", {}).get("status") != "connected":
                    raise RuntimeError("数字图书馆 MCP 未连接，请检查本机 HTTP 服务及 SSH 反向隧道")
                await self.step(emit, "图书馆 MCP", "passed", "数字图书馆已连接")
        finally:
            await tunnel.close()

    async def _finish(self, success, error=""):
        state = "SUCCEEDED" if success else "FAILED"
        operation = {**self.operation, "state": state, "finished_at": datetime.now(UTC).isoformat()}
        values = {
            "status": EnvironmentStatus.AVAILABLE if success else EnvironmentStatus.UNAVAILABLE,
            "last_checked_at": datetime.now(UTC),
            "status_detail": {"operation": operation, "checks": self.steps, "message": self.redact(error)},
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

    async def run(self, emit):
        success, error = False, ""
        try:
            async with asyncio.timeout(self.settings.remote_deploy_timeout_seconds):
                await self.step(emit, "SSH 连接与执行检查", "running")
                self.ssh = await self.runtime.open_session(self.environment)
                await self._native_idle()
                await self.step(emit, "SSH 连接与执行检查", "passed")
                if self.operation["action"] == "deploy":
                    await self._install(emit)
                await self._restart(emit)
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
            applied = await self._finish(success, error)
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
