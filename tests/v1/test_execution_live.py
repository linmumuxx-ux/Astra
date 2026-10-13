"""真实 Task API → Worker → 原生 Session → 待验收 → 人类独立复验/审批业务结果。

使用独立新库、工程和受密码保护 Runtime；默认跳过，显式消耗真实模型额度。
"""

import asyncio
import hashlib
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
from sqlalchemy import func, select

from apps.api.main import create_app
from apps.services.executions import ExecutionRunner
from domains.core import new_id, now
from domains.governance.models import BudgetUsage
from domains.identity.models import Actor
from domains.identity.service import digest, issue_credential
from domains.personas.models import InboxAdmission
from domains.runtime import OpenCodeClient, OpenCodeConfig, RuntimePurpose
from domains.runtime.execution_config import ExecutionSettings

from .http_server import serve_http
from .test_domains import post
from .test_runtime_live import _TESTS, run_command

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.getenv("ASTRA_LIVE_EXECUTION") != "1", reason="真实业务工程验收需显式启用"),
]


async def test_real_business_task_runtime_submission_and_independent_review(tmp_path, monkeypatch):
    physical = Path(os.getenv("ASTRA_LIVE_EXECUTION_ROOT", str(tmp_path))).resolve() / uuid4().hex
    physical.mkdir(parents=True)
    repository, storage, directory = physical / "project", physical / "workspaces", physical / "runtime"
    for path in [repository, storage, directory]:
        path.mkdir()
    (repository / "test_arithmetic.py").write_text(_TESTS)
    original_digest = hashlib.sha256(_TESTS.encode()).hexdigest()
    for args in [
        ("init", "-q"),
        ("add", "."),
        (
            "-c",
            "user.name=Astra Live",
            "-c",
            "user.email=live@example.invalid",
            "commit",
            "-qm",
            "acceptance baseline",
        ),
    ]:
        code, _, _ = await run_command(repository, "git", *args)
        assert code == 0
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
        actor = Actor(id=new_id(), name="真实业务验收负责人", kind="HUMAN", permissions=["*"])
        session.add(actor)
        await session.flush()
        token = await issue_credential(session, actor)
        human_id = actor.id
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    password = secrets.token_urlsafe(32)
    credential = physical / "worker-secret.json"
    credential.write_text(json.dumps({"password": password}))
    credential.chmod(0o600)
    binary = shutil.which("opencode")
    assert binary
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
    native = OpenCodeClient(
        OpenCodeConfig(
            f"http://127.0.0.1:{port}",
            "probe",
            RuntimePurpose.TASK,
            (str(storage),),
            model=model,
            password=password,
        )
    )
    report = {
        "kind": "real_business_task_execution",
        "result": "FAILED",
        "whole_system_acceptance": False,
        "evidence_root": str(physical),
        "started_at": time.time(),
    }
    report_path = Path(os.getenv("ASTRA_LIVE_EXECUTION_REPORT", str(physical / "report.json")))
    try:
        for _ in range(100):
            try:
                report["health"] = await native.verify_contract()
                break
            except Exception:
                if process.poll() is not None:
                    raise AssertionError("隔离 Runtime 启动失败") from None
                await asyncio.sleep(0.2)
        else:
            raise AssertionError("隔离 Runtime 未就绪")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://isolated",
            headers={"Authorization": f"Bearer {token}"},
        ) as api:
            team = (await post(api, "teams", {"name": "真实工程业务团队"})).json()
            role = (
                await post(
                    api,
                    "roles",
                    {
                        "team_id": team["id"],
                        "name": "工程主责",
                        "permissions": ["task.create", "task.dispatch", "task.review"],
                    },
                )
            ).json()
            employee = (
                await post(
                    api,
                    "employees",
                    {
                        "team_id": team["id"],
                        "role_id": role["id"],
                        "name": "真实工程主责员工",
                        "permissions": role["permissions"],
                        "scope": {"projects": ["arithmetic"]},
                    },
                )
            ).json()
            executor_token = secrets.token_urlsafe(48)
            executor = (
                await post(
                    api,
                    "system-identities/executors",
                    {
                        "name": "真实工程执行系统",
                        "team_ids": [team["id"]],
                        "credential_digest": digest(executor_token),
                    },
                )
            ).json()
            for aid, permissions in [
                (human_id, ["task.create", "task.dispatch", "task.review"]),
                (employee["id"], role["permissions"]),
                (executor["id"], ["task.reconcile"]),
            ]:
                result = await post(
                    api,
                    "workspace-grants",
                    {
                        "actor_id": aid,
                        "team_id": team["id"],
                        "project_id": "arithmetic",
                        "permissions": permissions,
                        "expires_at": now() + 3600,
                    },
                )
                assert result.status_code == 200, result.text
            worker = (
                await post(
                    api,
                    "workers",
                    {
                        "name": "受密码保护本机 Worker",
                        "base_url": f"http://127.0.0.1:{port}",
                        "capabilities": ["python"],
                        "allowed_projects": ["arithmetic"],
                        "workspace_roots": [str(storage)],
                    },
                )
            ).json()
            bound = await post(
                api,
                f"workers/{worker['id']}/credential",
                {"revision": worker["revision"], "credential_ref": f"file:{credential}"},
            )
            assert bound.status_code == 200 and "credential_ref" not in bound.json()
            probe = await post(api, f"workers/{worker['id']}/probe")
            assert probe.status_code == 200 and probe.json()["health"] == "HEALTHY"
            settings_dict = {
                "projects": {
                    worker["id"]: {
                        "arithmetic": {
                            "transport": "local",
                            "repository": str(repository),
                            "workspace_root": str(storage),
                            "base_ref": "HEAD",
                            "model": model,
                            "permission_rules": [
                                {"permission": "*", "pattern": "*", "action": "deny"},
                                *(
                                    {"permission": tool, "pattern": "*", "action": "allow"}
                                    for tool in ["read", "glob", "grep", "list", "edit"]
                                ),
                                {"permission": "edit", "pattern": "*test_arithmetic.py", "action": "deny"},
                                {
                                    "permission": "bash",
                                    "pattern": "python3 -m unittest -v",
                                    "action": "allow",
                                },
                            ],
                        }
                    }
                }
            }
            config_file = physical / "execution.json"
            config_file.write_text(json.dumps(settings_dict))
            config_file.chmod(0o600)
            monkeypatch.setenv("ASTRA_V1_EXECUTION_CONFIG", str(config_file))
            created = await post(
                api,
                "tasks",
                {
                    "team_id": team["id"],
                    "owner_employee_id": employee["id"],
                    "title": "真实 API 工程闭环",
                    "objective": (
                        "Create arithmetic.py defining add(a,b). Accept only int excluding bool, "
                        "reject invalid operands with TypeError. "
                        "Read test_arithmetic.py without modifying it. "
                        "Run exactly python3 -m unittest -v. No network or installs. "
                        "Do not change other files."
                    ),
                    "acceptance_criteria": ["五项原始测试实际通过，原始测试文件未修改"],
                    "required_capabilities": ["python"],
                    "asset_scope": {"project_id": "arithmetic"},
                },
            )
            assert created.status_code == 200, created.text
            task = created.json()
            dispatched = await post(api, f"tasks/{task['id']}/dispatch", {"worker_id": worker["id"]})
            assert dispatched.status_code == 200, dispatched.text
            execution_id = dispatched.json()["execution"]["id"]
            runner = ExecutionRunner(
                app.state.db, executor_token, ExecutionSettings.model_validate(settings_dict)
            )
            submitted = await runner.run(execution_id, timeout_seconds=180)
            assert submitted["state"] == "SUBMITTED"
            current = (await api.get(f"/api/v1/tasks/{task['id']}")).json()
            assert current["status"] == "REVIEW" and current["completed_at"] is None
            workspace = Path(submitted["workspace_ref"])
            assert (
                hashlib.sha256((workspace / "test_arithmetic.py").read_bytes()).hexdigest() == original_digest
            )
            code, stdout, stderr = await run_command(workspace, "python3", "-m", "unittest", "-v")
            assert code == 0
            evidence_response = await api.get(f"/api/v1/executions/{execution_id}/native-evidence")
            assert evidence_response.status_code == 200, evidence_response.text
            items = evidence_response.json()["items"]
            test_result = next(
                item
                for item in items
                if item["tool"] == "bash" and "OK" in item["output"] and "Ran 5 tests" in item["output"]
            )
            payload = {
                "execution_id": execution_id,
                "expected_task_revision": current["revision"],
                "outcome": "COMPLETED",
                "criteria_results": [
                    {
                        "criterion_index": 0,
                        "passed": True,
                        "reason": "人类独立复验退出码0且原始测试 SHA256 未变",
                        "evidence": [
                            {key: test_result[key] for key in ["native_session_id", "message_id", "part_id"]}
                            | {"excerpt": "Ran 5 tests"}
                        ],
                    }
                ],
            }
            if os.getenv("ASTRA_LIVE_UI") == "1":
                token_file = physical / "browser.token"
                token_file.write_text(token)
                token_file.chmod(0o600)
                ui_result = physical / "ui-result.json"
                async with serve_http(app) as api_url:
                    ui = await asyncio.create_subprocess_exec(
                        "node",
                        "e2e/review-live.mjs",
                        cwd=ROOT / "apps/web",
                        env={
                            **os.environ,
                            "ASTRA_API_URL": api_url,
                            "ASTRA_E2E_TOKEN_FILE": str(token_file),
                            "ASTRA_LIVE_TASK_ID": task["id"],
                            "ASTRA_LIVE_REVIEW_RESULT": str(ui_result),
                        },
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, ui_error = await asyncio.wait_for(ui.communicate(), timeout=90)
                    assert ui.returncode == 0, ui_error.decode(errors="replace")
                result = json.loads(ui_result.read_text())
                review_body, payload, operation_key = (
                    result["review"],
                    result["request_body"],
                    result["operation_key"],
                )
                report["real_browser_review_verified"] = True
            else:
                review = await post(api, f"tasks/{task['id']}/review", payload, key="independent-review")
                assert review.status_code == 200, review.text
                review_body, operation_key = review.json(), "independent-review"
            replay = await post(api, f"tasks/{task['id']}/review", payload, key=operation_key)
            assert replay.json()["id"] == review_body["id"]
            final = (await api.get(f"/api/v1/tasks/{task['id']}")).json()
            assert final["status"] == "COMPLETED" and final["latest_result"]["review_id"] == review_body["id"]
            async with app.state.db.sessions() as session:
                usage = (
                    await session.scalars(select(BudgetUsage).where(BudgetUsage.purpose == "TASK"))
                ).all()
                assert len(usage) == 1 and usage[0].tokens > 0
                admissions = await session.scalar(select(func.count(InboxAdmission.id)))
                assert admissions == 2
            report.update(
                result="PASSED",
                task_id=task["id"],
                execution_id=execution_id,
                native_session_id=submitted["native_session_id"],
                workspace=str(workspace),
                review_id=review_body["id"],
                reviewer_id=review_body["reviewer_id"],
                final_business_status=final["status"],
                native_evidence_refs=submitted["evidence_refs"],
                independent_test_exit_code=code,
                independent_test_output=stdout + stderr,
                original_test_sha256=original_digest,
                worker_credential_resolved=True,
                review_idempotency_verified=True,
                source_event_inbox_count=admissions,
                execution_tokens=usage[0].tokens,
                cost_micros=usage[0].cost_micros,
            )
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
        raise
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 10)
        log.close()
        await app.state.db.engine.dispose()
        report["finished_at"] = time.time()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
