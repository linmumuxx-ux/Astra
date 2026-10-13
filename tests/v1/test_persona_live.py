"""真实 OpenCode 短回合 + 跨 Session Git Memory；只用独立新库与决策目录。"""

import asyncio
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from apps.api.main import create_app
from apps.services.personas import PersonaRunner
from domains.core import new_id, now
from domains.governance.models import BudgetUsage
from domains.identity.models import Actor
from domains.identity.service import issue_credential
from domains.knowledge.memory import GitMemory
from domains.organization.models import TeamMember
from domains.personas.models import EmployeeTurn, InboxAdmission, Routine
from domains.runtime import OpenCodeClient, OpenCodeConfig, RuntimePurpose

from .test_domains import post

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("ASTRA_LIVE_PERSONA") != "1", reason="真实 Persona 验收需显式启用并配置 ASTRA_LIVE_MODEL"
    ),
]


async def test_real_persona_short_sessions_git_memory_and_authenticated_reply(tmp_path):
    physical = Path(os.environ.get("ASTRA_LIVE_PERSONA_ROOT", str(tmp_path))).resolve() / uuid4().hex
    physical.mkdir(parents=True)
    directory = physical / "decision"
    directory.mkdir()
    url = f"sqlite+aiosqlite:///{physical / 'new.db'}"
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "apps.api.manage", "migrate"],
        cwd=ROOT,
        env={**os.environ, "ASTRA_V1_DATABASE_URL": url},
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    app = create_app(url)
    async with app.state.db.sessions.begin() as session:
        human = Actor(id=new_id(), kind="HUMAN", name="真实持续记忆验收人", permissions=["*"])
        session.add(human)
        await session.flush()
        token = await issue_credential(session, human)
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    password = secrets.token_urlsafe(32)
    binary = shutil.which("opencode")
    assert binary, "需本机既有 OpenCode，不联网替换公司版本"
    log = (physical / "runtime.log").open("wb")
    process = subprocess.Popen(
        [binary, "serve", "--pure", "--hostname", "127.0.0.1", "--port", str(port)],
        cwd=directory,
        env={
            **os.environ,
            "OPENCODE_SERVER_PASSWORD": password,
            "OPENCODE_CONFIG_CONTENT": json.dumps({"permission": {"*": "deny"}}),
        },
        stdout=log,
        stderr=log,
    )
    model = os.environ["ASTRA_LIVE_MODEL"]
    client = OpenCodeClient(
        OpenCodeConfig(
            f"http://127.0.0.1:{port}",
            "persona-live-isolated",
            RuntimePurpose.PERSONA,
            (str(directory),),
            model=model,
            password=password,
        )
    )
    report = {
        "kind": "real_opencode_persona_memory",
        "result": "FAILED",
        "model": model,
        "whole_system_acceptance": False,
        "started_at": time.time(),
        "evidence_root": str(physical),
    }
    report_path = Path(os.getenv("ASTRA_LIVE_PERSONA_REPORT", str(physical / "report.json")))
    background = []
    background_logs = []
    try:
        for _ in range(100):
            try:
                report["health"] = await client.verify_contract()
                break
            except Exception:
                if process.poll() is not None:
                    raise AssertionError("隔离 Persona Runtime 启动失败") from None
                await asyncio.sleep(0.2)
        else:
            raise AssertionError("隔离 Persona Runtime 未就绪")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://isolated",
            headers={"Authorization": f"Bearer {token}"},
        ) as api:
            team = (await post(api, "teams", {"name": "真实 Persona 验收团队"})).json()
            role = (
                await post(
                    api,
                    "roles",
                    {
                        "name": "持续职责",
                        "team_id": team["id"],
                        "mandate": "持续记住已确认承诺，回复授权人的具体问题。",
                        "permissions": ["channel.send", "memory.write"],
                    },
                )
            ).json()
            employee = (
                await post(
                    api,
                    "employees",
                    {
                        "name": "记忆验收员工",
                        "team_id": team["id"],
                        "role_id": role["id"],
                        "permissions": role["permissions"],
                    },
                )
            ).json()
            dm = (await post(api, f"employees/{employee['id']}/dm")).json()
            async with app.state.db.sessions.begin() as session:
                service = Actor(kind="SYSTEM", name="隔离 Persona 服务", permissions=["persona.run"])
                session.add(service)
                await session.flush()
                session.add(TeamMember(team_id=team["id"], actor_id=service.id))
                service_token = await issue_credential(session, service)
            runner = PersonaRunner(app.state.db, service_token, client, GitMemory(str(physical / "memory")))
            codeword = "松柏-642"
            result = await post(
                api,
                f"channels/{dm['id']}/messages",
                {
                    "content": f"已确认的长期工作承诺：项目暗号是 {codeword}，请写入核心记忆供新会话使用。"
                    "本回合仅提出 remember 决策，不需要 reply，不创建工程任务。"
                },
            )
            assert result.status_code == 200
            first = await runner.run(employee["id"], timeout_seconds=150)
            assert first["status"] == "FINISHED"
            assert [action["type"] for action in first["actions"]] == ["remember"]
            result = await post(
                api,
                f"channels/{dm['id']}/messages",
                {
                    "content": (
                        "现在是新的决策会话，请从核心记忆复述此前已确认的项目暗号。"
                        "仅提出 reply 决策，不修改记忆。"
                    )
                },
            )
            assert result.status_code == 200
            # 重建运行器不依赖前一个 Python 对象或模型 Session。
            restarted = PersonaRunner(
                app.state.db, service_token, client, GitMemory(str(physical / "memory"))
            )
            second = await restarted.run(employee["id"], timeout_seconds=150)
            assert second["status"] == "FINISHED"
            messages = (await api.get(f"/api/v1/channels/{dm['id']}/messages")).json()
            replies = [item for item in messages if item["sender_id"] == employee["id"]]
            assert len(replies) == 1 and codeword in replies[0]["content"]
            assert (await api.get("/api/v1/tasks")).json() == []
            if os.getenv("ASTRA_LIVE_CELERY") == "1":
                redis = shutil.which("redis-server")
                assert redis, "真实队列验收需要本机既有 redis-server"
                with socket.socket() as reserved:
                    reserved.bind(("127.0.0.1", 0))
                    redis_port = reserved.getsockname()[1]
                redis_log = (physical / "redis.log").open("wb")
                background_logs.append(redis_log)
                background.append(
                    subprocess.Popen(
                        [
                            redis,
                            "--bind",
                            "127.0.0.1",
                            "--port",
                            str(redis_port),
                            "--save",
                            "",
                            "--appendonly",
                            "no",
                            "--dir",
                            str(physical),
                        ],
                        stdout=redis_log,
                        stderr=redis_log,
                    )
                )
                async with app.state.db.sessions.begin() as session:
                    scheduler = Actor(kind="SYSTEM", name="隔离职责投递器", permissions=["routine.signal"])
                    session.add(scheduler)
                    await session.flush()
                    session.add(TeamMember(team_id=team["id"], actor_id=scheduler.id))
                    scheduler_token = await issue_credential(session, scheduler)
                    routine = Routine(
                        employee_id=employee["id"],
                        title="检查当前无任务时静默记档，选择 no_action，不创建任务或发消息",
                        kind="INTERVAL",
                        schedule="3600",
                        timezone="Asia/Shanghai",
                        next_due_at=now() - 1,
                    )
                    session.add(routine)
                for name, value in [("persona", service_token), ("scheduler", scheduler_token)]:
                    path = physical / f"{name}.token"
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "w") as secret_file:
                        secret_file.write(value)
                queue_log = (physical / "queue.log").open("wb")
                background_logs.append(queue_log)
                background.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "celery",
                            "-A",
                            "apps.services.celery_app",
                            "worker",
                            "--pool=solo",
                            "--concurrency=1",
                            "--beat",
                            "--schedule",
                            str(physical / "beat"),
                            "--loglevel=WARNING",
                            "--without-gossip",
                            "--without-mingle",
                        ],
                        cwd=ROOT,
                        env={
                            **os.environ,
                            "ASTRA_V1_DATABASE_URL": url,
                            "ASTRA_V1_BROKER_URL": f"redis://127.0.0.1:{redis_port}/0",
                            "ASTRA_V1_PERSONA_CREDENTIAL_FILE": str(physical / "persona.token"),
                            "ASTRA_V1_SCHEDULER_CREDENTIAL_FILE": str(physical / "scheduler.token"),
                            "ASTRA_V1_PERSONA_URL": f"http://127.0.0.1:{port}",
                            "ASTRA_V1_PERSONA_DIRECTORY": str(directory),
                            "ASTRA_V1_PERSONA_MODEL": model,
                            "ASTRA_V1_PERSONA_PASSWORD": password,
                            "ASTRA_V1_MEMORY_ROOT": str(physical / "memory"),
                        },
                        stdout=queue_log,
                        stderr=queue_log,
                    )
                )
                deadline = time.monotonic() + 100
                while time.monotonic() < deadline:
                    async with app.state.db.sessions() as session:
                        third = await session.scalar(
                            select(EmployeeTurn).where(
                                EmployeeTurn.employee_id == employee["id"],
                                EmployeeTurn.fence == 3,
                                EmployeeTurn.status == "FINISHED",
                            )
                        )
                        if third:
                            assert [item["type"] for item in third.actions] == ["no_action"]
                            break
                    assert all(child.poll() is None for child in background), "隔离队列进程退出"
                    await asyncio.sleep(0.5)
                else:
                    raise AssertionError("真实 Beat/Redis/Celery 职责未形成已处理回合")
                report["routine_redis_celery_beat_verified"] = True
        async with app.state.db.sessions() as session:
            turns = (await session.scalars(select(EmployeeTurn))).all()
            admissions = (await session.scalars(select(InboxAdmission))).all()
            usage = (await session.scalars(select(BudgetUsage))).all()
            expected = 3 if os.getenv("ASTRA_LIVE_CELERY") == "1" else 2
            assert len(turns) == expected and len({turn.native_session_id for turn in turns}) == expected
            assert all(
                item.observed_at and item.disposition in {"HANDLED", "NO_ACTION"} for item in admissions
            )
            assert len(usage) == expected and all(item.tokens > 0 for item in usage)
            report.update(
                result="PASSED",
                native_session_ids=[turn.native_session_id for turn in turns],
                distinct_short_sessions=True,
                cross_session_memory_verified=True,
                authenticated_employee_reply=True,
                no_task_created=True,
                decision_tokens=sum(item.tokens for item in usage),
                native_cost_micros=sum(item.cost_micros for item in usage),
            )
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
        raise
    finally:
        for child in reversed(background):
            child.terminate()
            try:
                await asyncio.to_thread(child.wait, timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                await asyncio.to_thread(child.wait, timeout=5)
        for handle in background_logs:
            handle.close()
        process.terminate()
        await asyncio.to_thread(process.wait, timeout=15)
        log.close()
        await app.state.db.engine.dispose()
        report["finished_at"] = time.time()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
