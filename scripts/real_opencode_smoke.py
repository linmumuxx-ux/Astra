#!/usr/bin/env python3
"""Run one real Astra task through OpenCode Server in an isolated workspace."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from sqlalchemy import select

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="opencode/glm-5.1",
        help="OpenCode provider/model identifier",
    )
    parser.add_argument(
        "--opencode",
        default="opencode",
        help="Local OpenCode executable or absolute path",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the isolated database, workspace and work records after success",
    )
    return parser.parse_args()


async def run_smoke(
    temp_root: Path,
    model: str,
    opencode_binary: str,
    server_url: str,
) -> dict[str, object]:
    database_path = temp_root / "astra-smoke.db"
    employee_workspace = temp_root / "employee-workspace"
    observation_root = temp_root / "observations"
    employee_workspace.mkdir()
    observation_root.mkdir()

    os.environ.update(
        {
            "ASTRA_DATABASE_URL": f"sqlite+aiosqlite:///{database_path}",
            "ASTRA_WORKSPACE_ROOT": str(observation_root),
            "ASTRA_SEED_DEMO": "false",
            "ASTRA_OPENCODE_BINARY": opencode_binary,
            "ASTRA_OPENCODE_MODEL": model,
            "ASTRA_OPENCODE_TIMEOUT_SECONDS": "300",
            "ASTRA_EXECUTOR_TYPE": "opencode_server",
            "ASTRA_OPENCODE_SERVER_URL": server_url,
        }
    )

    from app.database import SessionLocal, init_database
    from app.domain import EmployeeStatus, EnvironmentStatus, RunStatus, TaskStatus
    from app.models import DigitalEmployee, OpenCodeExecutionEnvironment, Run, Task
    from app.runtime.coordinator import TaskCoordinator
    from app.schemas import TaskCreate
    from app.services import TaskService

    await init_database()
    async with SessionLocal() as session:
        employee_id = "astra-real-smoke"
        employee = DigitalEmployee(
            id=employee_id,
            name="Astra Real Smoke",
            role="本地 OpenCode 验收员工",
            status=EmployeeStatus.WORKING,
            task_types=["ISSUE"],
            category_ids=["testing-platform"],
            enabled=True,
            auto_claim=False,
            auto_execute=False,
            current_task_count=1,
        )
        session.add(employee)
        session.add(
            OpenCodeExecutionEnvironment(
                employee_id=employee_id,
                mode="LOCAL",
                name="真实验收工作空间",
                opencode_path=opencode_binary,
                workspace_root=str(employee_workspace),
                status=EnvironmentStatus.AVAILABLE,
            )
        )
        await session.commit()
        task = await TaskService(session).create(
            TaskCreate(
                source="manual",
                task_type="ISSUE",
                category_id="testing-platform",
                title="验证 Astra 本地 OpenCode 执行链路",
                description=(
                    "在当前工作空间创建 astra-opencode-smoke.txt，文件内容必须恰好为 "
                    "ASTRA_V04_OPENCODE_OK（末尾换行允许）。完成后简短说明结果。"
                ),
                acceptance_criteria=[
                    {"content": "astra-opencode-smoke.txt 已创建"},
                    {"content": "文件内容为 ASTRA_V04_OPENCODE_OK"},
                ],
                employee_id=employee_id,
                priority="LOW",
                completion_policy="AUTO",
            )
        )
        await TaskService(session).transition(
            task,
            TaskStatus.RUNNING,
            current_progress="开始真实 OpenCode 验证",
            message="真实验收任务开始",
        )
        task_id = task.id

    await TaskCoordinator().process(task_id)

    output_path = employee_workspace / "astra-opencode-smoke.txt"
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        run = await session.scalar(select(Run).where(Run.task_id == task_id))

    output_content = (
        output_path.read_text(encoding="utf-8").strip()
        if output_path.exists()
        else None
    )
    summary = {
        "task_id": task_id,
        "task_status": task.status if task else None,
        "run_id": run.id if run else None,
        "run_status": run.status if run else None,
        "exit_code": run.exit_code if run else None,
        "session_id": run.opencode_session_id if run else None,
        "model_name": run.model_name if run else None,
        "executor_type": run.executor_type if run else None,
        "total_tokens": run.total_tokens if run else None,
        "tool_calls": run.tool_call_count if run else None,
        "output_file_exists": output_path.exists(),
        "output_file_content": output_content,
    }
    expected = {
        "task_status": TaskStatus.COMPLETED,
        "run_status": RunStatus.COMPLETED,
        "exit_code": 0,
        "model_name": model,
        "executor_type": "opencode_server",
        "output_file_exists": True,
        "output_file_content": "ASTRA_V04_OPENCODE_OK",
    }
    failures = [
        f"{key}: expected {value!r}, got {summary.get(key)!r}"
        for key, value in expected.items()
        if summary.get(key) != value
    ]
    if not summary["session_id"]:
        failures.append("session_id: missing")
    if summary["total_tokens"] is None:
        failures.append("total_tokens: missing")
    if not summary["tool_calls"]:
        failures.append("tool_calls: missing")
    if failures:
        raise RuntimeError("真实 OpenCode 验收失败：" + "; ".join(failures))
    return summary


def main() -> int:
    args = parse_args()
    temp_root = Path(
        tempfile.mkdtemp(prefix=".astra-opencode-smoke-", dir=REPOSITORY_ROOT)
    )
    succeeded = False
    server = None
    try:
        from opencode_server_poc import ManagedServer

        server = ManagedServer(args.opencode, temp_root, 300)
        server_url = server.start()
        summary = asyncio.run(
            run_smoke(temp_root, args.model, args.opencode, server_url)
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        succeeded = True
        return 0
    except Exception as exc:  # noqa: BLE001 - preserve the isolated smoke-test site on any failure
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if server:
            server.stop()
        if succeeded and not args.keep:
            shutil.rmtree(temp_root)
        else:
            print(f"验收现场：{temp_root}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
