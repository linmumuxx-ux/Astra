#!/usr/bin/env python3
"""Phase 1B real OpenCode verification: session-anchored experience.

Against a real local OpenCode Server:
  1. Run one task to SUCCEEDED and capture the real runtime_context token.
  2. Submit a candidate experience through the MCP service layer using that token.
  3. Verify the source Session is bound, the fingerprint exists, and the
     SUCCEEDED Session verification reconcile marks the candidate verified.
  4. Record whether the real model also invoked the MCP tool on its own.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def configure(root: Path, workspace: Path, port: int, model: str, binary: str) -> None:
    os.environ.update(
        {
            "ASTRA_DATABASE_URL": f"sqlite+aiosqlite:///{root / 'phase1b.db'}",
            "ASTRA_WORKSPACE_ROOT": str(workspace),
            "ASTRA_RUNTIME_DIR": str(root / "runtime"),
            "ASTRA_SEED_DEMO": "false",
            "ASTRA_OPENCODE_BINARY": binary,
            "ASTRA_OPENCODE_MODEL": model,
            "ASTRA_OPENCODE_TIMEOUT_SECONDS": "300",
            "ASTRA_MCP_TRANSPORT": "stdio",
        }
    )


def extract_runtime_token(messages: list[dict]) -> str | None:
    for message in messages:
        for part in message.get("parts", []):
            if not isinstance(part, dict) or not part.get("synthetic"):
                continue
            text = part.get("text", "")
            marker = "ASTRA_RUNTIME_CONTEXT:"
            if marker in text:
                return text.split(marker, 1)[1].strip().split()[0]
    return None


async def run(model: str, binary: str) -> dict:
    root = Path(tempfile.mkdtemp(prefix="phase1b-"))
    workspace = root / "employee-ws"
    workspace.mkdir()
    port = free_port()
    configure(root, workspace, port, model, binary)

    from app.config.settings import get_settings

    get_settings.cache_clear()

    from app.database import SessionLocal, init_database
    from app.models import (
        DigitalEmployee,
        KnowledgeItem,
        OpenCodeExecutionEnvironment,
        RuntimeSession,
        Task,
    )
    from app.runtime.environment import environment_snapshot
    from app.runtime.lifecycle import RuntimeService

    await init_database()
    async with SessionLocal() as session:
        employee = DigitalEmployee(
            id="phase1b",
            name="Phase 1B Real",
            role="build",
            status="IDLE",
            task_types=["ISSUE"],
            category_ids=[],
            enabled=True,
            auto_claim=False,
            auto_execute=False,
        )
        environment = OpenCodeExecutionEnvironment(
            employee_id="phase1b",
            mode="LOCAL",
            name="Phase 1B",
            opencode_path=binary,
            workspace_root=str(workspace),
            opencode_server_port=port,
            model_name=model,
            status="AVAILABLE",
        )
        session.add_all([employee, environment])
        await session.commit()
        session.add(
            Task(
                id="T-EXP",
                title="Phase 1B experience",
                task_type="ISSUE",
                status="PENDING",
                employee_id="phase1b",
                description=(
                    "请完成两步：\n"
                    "1. 创建文件 phase1b.txt，内容为 PHASE1B_OK。\n"
                    "2. 调用 MCP 工具 astra_library_library_submit_experience 提交一条经验："
                    "title=Phase1B 经验，summary=真实会话经验，content_md=创建文件并验证，"
                    "experience_type=fix；runtime_context 参数必须使用内部运行上下文里 "
                    "ASTRA_RUNTIME_CONTEXT 后面的令牌。\n"
                    "完成后回复 EXPERIENCE_DONE。"
                ),
                acceptance_criteria=[{"id": "AC-01", "content": "文件已创建"}],
                execution_environment_snapshot=environment_snapshot(environment),
            )
        )
        await session.commit()

    async with SessionLocal() as session:
        await RuntimeService(session).start("T-EXP")

    deadline = time.monotonic() + 240
    status = "PENDING"
    while time.monotonic() < deadline:
        async with SessionLocal() as session:
            await RuntimeService(session).refresh("T-EXP")
            task = await session.get(Task, "T-EXP")
            status = task.status
            if status in {"SUCCEEDED", "FAILED", "CANCELED"}:
                break
        await asyncio.sleep(2)

    from app.library_schemas import LibrarySubmitExperienceInput
    from app.library_service import KnowledgeService
    from app.runtime.session_connection import connect, resolve_environment

    result: dict = {"task_status": status}
    async with SessionLocal() as session:
        task = await session.get(Task, "T-EXP")
        runtime_session = await session.get(RuntimeSession, task.current_session_id)
        result["session_status"] = runtime_session.status
        environment = await resolve_environment(session, task)
        async with connect(environment) as client:
            messages = await client.messages(Path(task.workspace), task.current_session_id)
        result["token_in_session"] = extract_runtime_token(messages) is not None
        result["model_called_mcp"] = any(
            isinstance(part, dict)
            and "library_submit_experience" in str(part.get("tool", ""))
            for message in messages
            for part in message.get("parts", [])
        )
        token = extract_runtime_token(messages)
        service = KnowledgeService(session)
        detail = await service.mcp_submit_experience(
            LibrarySubmitExperienceInput(
                title="Phase1B 经验",
                summary="真实会话经验",
                content_md="创建文件并验证",
                experience_type="fix",
            ),
            runtime_context=token,
        )
        item = await session.get(KnowledgeItem, detail.id)
        result["source_session_id"] = item.source_session_id
        result["origin"] = item.origin
        result["fingerprint"] = bool(item.fingerprint)
        result["verification_status"] = item.verification_status
        result["verification_session_status"] = item.verification_session_status
        result["verified_at"] = item.verified_at is not None
        result["source_status_snapshot"] = (item.source_ref_snapshot or {}).get("session_id")

    result["workspace"] = str(workspace)
    result["root"] = str(root)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="deepseek/deepseek-flash")
    parser.add_argument("--opencode", default="opencode")
    args = parser.parse_args()
    result = asyncio.run(run(args.model, args.opencode))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    passed = (
        result["task_status"] == "SUCCEEDED"
        and result["session_status"] == "SUCCEEDED"
        and result["token_in_session"]
        and result["source_session_id"]
        and result["origin"] == "runtime"
        and result["fingerprint"]
        and result["verification_status"] == "verified"
        and result["verification_session_status"] == "SUCCEEDED"
        and result["verified_at"]
    )
    if passed:
        shutil.rmtree(result["root"], ignore_errors=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())