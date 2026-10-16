#!/usr/bin/env python3
"""真实员工 OpenCode → 人工确认 → 真实复盘 → 跨任务复用 → HTTP 人工发布。

所有数据库、git worktree、进程及文件均隔离在临时目录；不写正式 Wiki。
运行：.venv/bin/python tools/e2e/verify_task_review_real.py --model deepseek/deepseek-flash
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "task-platform"))


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def run(model: str, binary: str, timeout: int):
    import httpx

    root = Path(tempfile.mkdtemp(prefix="astra-review-real-"))
    employee_port, assistant_port, api_port = (free_port() for _ in range(3))
    workspace = root / "employee"
    workspace.mkdir()
    os.environ.update({
        "ASTRA_DATABASE_URL": f"sqlite+aiosqlite:///{root / 'astra.db'}",
        "ASTRA_WORKSPACE_ROOT": str(root), "ASTRA_RUNTIME_DIR": str(root / "runtime"),
        "ASTRA_SEED_DEMO": "false", "ASTRA_LLM_WIKI_ENABLED": "false",
        "ASTRA_ASSISTANT_ENABLED": "true", "ASTRA_ASSISTANT_MODEL": model,
        "ASTRA_ASSISTANT_OPENCODE_URL": f"http://127.0.0.1:{assistant_port}",
        "ASTRA_ASSISTANT_OPENCODE_PASSWORD": "", "ASTRA_OPENCODE_SERVER_PASSWORD": "",
        "ASTRA_OPENCODE_BINARY": binary, "ASTRA_OPENCODE_MODEL": model,
        "PYTHONPATH": str(ROOT / "services" / "task-platform"),
    })
    from app.config.settings import get_settings
    get_settings.cache_clear()
    from sqlalchemy import select

    from app.assistant.client import AssistantOpenCodeClient
    from app.assistant.review import reconcile_task_reviews
    from app.assistant.server import AssistantOpenCodeServerManager
    from app.database import SessionLocal, engine
    from app.executors.opencode_server import OpenCodeServerClient
    from app.library_service import KnowledgeService, LibraryPrincipal
    from app.models import (
        Base,
        DigitalEmployee,
        ExperienceEvidence,
        KnowledgeItem,
        OpenCodeExecutionEnvironment,
        RuntimeSession,
        Task,
        TaskReview,
        TaskSummary,
    )
    from app.runtime.environment import environment_snapshot
    from app.runtime.lifecycle import RuntimeService

    # A committed seed creates genuine independent task git worktrees.
    subprocess.run(["git", "init", str(workspace)], check=True, capture_output=True)
    (workspace / "README.md").write_text("临时验证仓库\n")
    subprocess.run(["git", "-C", str(workspace), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(workspace), "-c", "user.name=Astra Verify", "-c",
                    "user.email=verify@localhost", "commit", "-m", "test: seed"],
                   check=True, capture_output=True)
    processes, handles = [], []

    def start(name, command, cwd, environment):
        handle = (root / f"{name}.log").open("w")
        handles.append(handle)
        process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=handle, stderr=subprocess.STDOUT)
        processes.append(process)
        return process

    employee_env = os.environ.copy()
    employee_env.pop("OPENCODE_SERVER_PASSWORD", None)
    employee_env["PATH"] = os.pathsep.join((str(Path(sys.executable).parent), employee_env.get("PATH", "")))
    start("employee", [binary, "serve", "--hostname", "127.0.0.1", "--port", str(employee_port)],
          workspace, employee_env)
    start("assistant", [binary, "serve", "--hostname", "127.0.0.1", "--port", str(assistant_port)],
          ROOT, AssistantOpenCodeServerManager(get_settings()).process_environment())
    started = time.monotonic()
    report = {"root": str(root), "model": model, "checks": {}, "wiki_sync": "disabled_in_isolated_test"}
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as http:
            for port in (employee_port, assistant_port):
                deadline = time.monotonic() + 45
                while True:
                    try:
                        response = await http.get(f"http://127.0.0.1:{port}/global/health")
                        if response.is_success and response.json().get("healthy"):
                            break
                    except httpx.RequestError:
                        pass
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"OpenCode {port} 未就绪：{root}")
                    await asyncio.sleep(0.5)
        assistant = AssistantOpenCodeClient()
        mcp = await assistant._inner.request("GET", "/mcp", directory=assistant.workspace)
        assert mcp["nexus-assistant"]["status"] == "connected", mcp
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            employee = DigitalEmployee(id="verify", name="真实验证员工", role="build", auto_claim=False)
            env = OpenCodeExecutionEnvironment(
                employee_id=employee.id, mode="LOCAL", name="隔离真实执行", workspace_root=str(workspace),
                opencode_server_port=employee_port, model_name=model,
                status="AVAILABLE", opencode_path=binary,
            )
            session.add_all([employee, env])
            await session.commit()
            snapshot = environment_snapshot(env)
        native = OpenCodeServerClient(get_settings(), base_url=f"http://127.0.0.1:{employee_port}")
        for index in (1, 2):
            task_id = f"T-REAL-{index}"
            async with SessionLocal() as session:
                session.add(Task(
                    id=task_id, title=["修复中文 JSON 展示", "修复 Unicode 导出内容匹配"][index - 1],
                    task_type="ISSUE", employee_id="verify", status="PENDING",
                    execution_environment_snapshot=snapshot,
                    description=(
                        "下游对 JSON 文件做中文字面匹配，标准库 json.dumps 默认将中文转义导致匹配失败。"
                        "在当前工作区写一个最小 Python 回归脚本：先复现默认输出不含中文字面的现象，"
                        "再用 ensure_ascii=False 和 UTF-8 写入 result.json；断言文件含中文字面且 json.loads "
                        "往返数据相同。实际执行脚本，成功输出 UNICODE_ROUNDTRIP_PASS，最后简述原因与验证。"
                        "只处理任务，不生成或提交经验。"
                    ),
                    acceptance_criteria=[{"id": "AC-1", "content": "真实运行断言并输出通过标记"}],
                ))
                await session.commit()
                task = await RuntimeService(session).start(task_id)
                sid, directory = task.current_session_id, Path(task.workspace)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                messages = await native.messages(directory, sid)
                final = [m for m in messages if m["info"].get("role") == "assistant"]
                if final and final[-1]["info"].get("finish") in {"stop", "end_turn"}:
                    assert not final[-1]["info"].get("error"), final[-1]["info"]["error"]
                    break
                await asyncio.sleep(1)
            else:
                raise TimeoutError(f"员工未结束 {task_id}：{root}")
            assert any("UNICODE_ROUNDTRIP_PASS" in str(p.get("state", {}).get("output", ""))
                       for m in messages for p in m.get("parts", [])), "缺少真实工具验证"
            assert (directory / "result.json").exists()
            assert await reconcile_task_reviews() == [], "未人工确认不得复盘"
            async with SessionLocal() as session:
                # Deliberately bypass the observer: confirmation must capture native terminal facts itself.
                await RuntimeService(session).confirm_completion(task_id)
                assert (await session.get(RuntimeSession, sid)).status == "SUCCEEDED"
            assert await reconcile_task_reviews() == [task_id]
            assert await reconcile_task_reviews() == [], "重复扫描不得重复调度"
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                async with SessionLocal() as session:
                    job = await session.scalar(select(TaskReview).where(TaskReview.task_id == task_id))
                    if job and job.status == "completed":
                        report["checks"][task_id] = dict(job.result)
                        break
                await asyncio.sleep(1)
            else:
                raise TimeoutError(f"复盘未提交 {task_id}：{root}")
        async with SessionLocal() as session:
            items = (await session.scalars(select(KnowledgeItem))).all()
            assert items and all(i.status == "candidate" for i in items)
            task_ids = (await session.scalars(select(Task.id))).all()
            per_task = {}
            for task_id in task_ids:
                refs = (await session.scalars(select(ExperienceEvidence.knowledge_id).where(
                    ExperienceEvidence.task_id == task_id))).all()
                per_task[task_id] = set(refs)
            assert per_task["T-REAL-1"] & per_task["T-REAL-2"], "真实模型应复用同一方法的经验"
            assert len(items) <= 2, "同一问题不应拆分大量经验"
            report["checks"]["cross_task_reuse"] = True
            report["checks"]["summary_count"] = len((await session.scalars(select(TaskSummary))).all())
            report["checks"]["experience_count"] = len(items)
            report["checks"]["verified_experiences"] = sum(i.verification_status == "verified" for i in items)
            candidate_id = items[0].id
            # Normal employee-visible DB queries exclude candidates.
            visible = await KnowledgeService(session).list_knowledge(
                LibraryPrincipal(user_id="employee", role="viewer"),
            )
            assert visible.total == 0
        start("api", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                      "--port", str(api_port)], ROOT / "services" / "task-platform", os.environ.copy())
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{api_port}", timeout=15, trust_env=False,
        ) as http:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    if (await http.get("/api/health")).is_success:
                        break
                except httpx.RequestError:
                    pass
                await asyncio.sleep(0.5)
            detail = (await http.get("/api/tasks/T-REAL-2/review")).json()
            assert detail["status"] == "completed" and detail["summary"] and detail["experiences"]
            assert (await http.post("/api/tasks/T-REAL-2/review/retry")).json()["status"] == "completed"
            viewer = {"X-Astra-Role": "viewer", "X-Astra-User-Id": "employee"}
            assert (await http.post(f"/api/library/knowledge/{candidate_id}/publish",
                                   json={"space_id": "general"}, headers=viewer)).status_code == 403
            reviewer = {"X-Astra-Role": "reviewer", "X-Astra-User-Id": "human-reviewer"}
            space = await http.post("/api/library/spaces", json={"name": "真实复盘验证"},
                                    headers={"X-Astra-Role": "admin"})
            space.raise_for_status()
            published = await http.post(f"/api/library/knowledge/{candidate_id}/publish",
                                        json={"space_id": space.json()["id"]}, headers=reviewer)
            published.raise_for_status()
            assert published.json()["status"] == "published"
            report["checks"]["human_publish_http"] = True
            report["checks"]["viewer_publish_denied"] = True
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return report
    finally:
        (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for handle in handles:
            handle.close()
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--opencode", default="opencode")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.model, args.opencode, args.timeout)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
