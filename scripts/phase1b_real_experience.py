#!/usr/bin/env python3
"""Isolated real-assistant acceptance over deterministic execution-session fixtures.

Exercises the actual OpenCode assistant, Skill, MCP, database and candidate flow.
Only the employee-session HTTP source is a fixture; it includes early human
corrections, question answers and enough messages to require pagination.
No employee is asked to output experiences or special result JSON.
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
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


OLD_PROTOCOL = "ASTRA_RESULT_JSON"
PROTOCOL_NEGATIONS = ("不", "无需", "废弃", "无关", "旧", "历史", "禁止")


def _promotes_abandoned_protocol(text: str) -> bool:
    """True when a historical output protocol is stated as a current requirement.

    A negative or historical mention ("旧协议已废弃，不得沿用") is allowed; a
    command-style statement ("最终回复必须追加 ASTRA_RESULT_JSON") is not.
    """
    if "以后必须" in text:
        return True
    for sentence in text.replace("\n", "。").split("。"):
        if OLD_PROTOCOL in sentence and not any(m in sentence for m in PROTOCOL_NEGATIONS):
            return True
    return False


def message(index, role, text):
    return {
        "info": {"id": f"msg_{index:04}", "role": role},
        "parts": [{"id": f"prt_{index:04}", "type": "text", "text": text}],
    }


def fixtures():
    requirement = [
        message(1, "user", "需求：隐藏已停用账号。"),
        message(2, "assistant", "我将删除已停用账号及历史记录。当时的历史 Runtime 协议还要求"
                               "最终追加 ASTRA_RESULT_JSON。"),
        message(
            3,
            "user",
            "纠正：绝对不能删除数据！只在默认列表隐藏，审计历史必须保留，并提供显示停用项开关。",
        ),
        message(
            4,
            "assistant",
            "改为默认过滤停用账号，保留存储与审计历史，增加显示停用项开关。",
        ),
    ]
    for index in range(5, 65):
        requirement.append(
            message(index, "assistant", f"执行检查 {index}，尚未发现其他问题。")
        )
    requirement.append(
        message(
            65,
            "assistant",
            "工作完成。默认列表隐藏、开关显示、审计查询和数据库保留测试全部通过。",
        )
    )
    issue = [
        message(1, "user", "问题：更新配置后界面仍显示旧值。"),
        message(2, "assistant", "可能是网络丢包，先重试请求。"),
        message(
            3,
            "user",
            "补充：直连数据库可读到新值；绕过缓存的接口也返回新值，只有普通接口仍然是旧值。",
        ),
        {
            "info": {"id": "msg_0004", "role": "assistant"},
            "parts": [
                {
                    "id": "prt_question",
                    "type": "tool",
                    "tool": "question",
                    "state": {
                        "input": {"questions": [{"question": "缓存键是否包含租户？"}]},
                        "metadata": {
                            "answers": [
                                ["包含租户；写路径漏传租户，删除了错误的缓存键。"]
                            ]
                        },
                        "output": "用户回答：包含租户；写路径漏传租户，删除了错误的缓存键。",
                    },
                }
            ],
        },
        message(
            5,
            "assistant",
            "根因：写路径构造失效键时遗漏租户。已统一读写键构造，并验证两个租户更新后读值正确且互不影响。",
        ),
    ]
    trivial = [message(1, "user", "请回复收到。"), message(2, "assistant", "收到。")]
    return {"ses_requirement": requirement, "ses_issue": issue, "ses_trivial": trivial}


async def run(model: str | None, binary: str, timeout: int):
    root = Path(tempfile.mkdtemp(prefix="astra-review-acceptance-"))
    # The assistant is a project-level agent: it loads Astra's project root
    # (.opencode/agents, .opencode/skills, opencode.json) with no workspace copy.
    workspace = ROOT
    data, reads = fixtures(), {key: set() for key in fixtures()}

    class Source(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            segments = parsed.path.strip("/").split("/")
            sid = segments[1] if len(segments) > 1 else ""
            if sid not in data:
                self.send_error(404)
                return
            query = parse_qs(parsed.query)
            if segments[-1] == "children":
                result = []
            else:
                before = query.get("before", [None])[0]
                limit = int(query.get("limit", [20])[0])
                end = int(before.removeprefix("cursor:")) if before else len(data[sid])
                start = max(0, end - limit)
                result = data[sid][start:end]
                reads[sid].update(m["info"]["id"] for m in result)
            content = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if segments[-1] != "children" and start:
                self.send_header("x-next-cursor", f"cursor:{start}")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_args):
            pass

    source = ThreadingHTTPServer(("127.0.0.1", 0), Source)
    threading.Thread(target=source.serve_forever, daemon=True).start()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    os.environ.update(
        {
            "ASTRA_DATABASE_URL": f"sqlite+aiosqlite:///{root / 'review.db'}",
            "ASTRA_SEED_DEMO": "false",
            "ASTRA_LLM_WIKI_ENABLED": "false",
            "ASTRA_ASSISTANT_ENABLED": "true",
            "ASTRA_ASSISTANT_OPENCODE_URL": f"http://127.0.0.1:{port}",
            "ASTRA_ASSISTANT_OPENCODE_PASSWORD": "",
            "PYTHONPATH": str(ROOT / "backend"),
        }
    )
    if model:
        os.environ["ASTRA_ASSISTANT_MODEL"] = model
    from app.config.settings import get_settings

    get_settings.cache_clear()
    from sqlalchemy import select

    from app.assistant.client import AssistantOpenCodeClient
    from app.assistant.review import reconcile_task_reviews
    from app.assistant.server import AssistantOpenCodeServerManager
    from app.database import SessionLocal, engine
    from app.models import (
        Base,
        DigitalEmployee,
        KnowledgeItem,
        OpenCodeExecutionEnvironment,
        RuntimeSession,
        Task,
        TaskSummary,
    )
    from app.runtime.environment import environment_snapshot

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        employee = DigitalEmployee(id="E1", name="执行事实来源", role="build")
        env = OpenCodeExecutionEnvironment(
            employee_id="E1",
            name="fixture",
            mode="LOCAL",
            workspace_root=str(root),
            status="AVAILABLE",
            opencode_server_port=source.server_port,
        )
        session.add_all([employee, env])
        await session.flush()
        for index, (sid, messages) in enumerate(data.items()):
            task_id = f"T{index}"
            session.add(
                Task(
                    id=task_id,
                    title=["隐藏停用账号", "配置缓存问题", "回复收到"][index],
                    description=messages[0]["parts"][0]["text"],
                    task_type="ISSUE" if index == 1 else "REQUIREMENT",
                    status="SUCCEEDED",
                    employee_id="E1",
                    current_session_id=sid,
                    last_message_id="msg_0001",
                )
            )
            session.add(
                RuntimeSession(
                    id=sid,
                    task_id=task_id,
                    employee_id="E1",
                    workspace=str(root),
                    environment=environment_snapshot(env),
                    status="SUCCEEDED",
                    last_message_id=messages[-1]["info"]["id"],
                )
            )
        await session.commit()
    environment = AssistantOpenCodeServerManager(get_settings()).process_environment()
    log = (root / "opencode.log").open("w")
    process = subprocess.Popen(
        [binary, "serve", "--hostname", "127.0.0.1", "--port", str(port)],
        cwd=workspace,
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        client = AssistantOpenCodeClient()
        deadline = time.monotonic() + 40
        while True:
            try:
                await client.health()
                break
            except Exception:
                if time.monotonic() > deadline or process.poll() is not None:
                    raise RuntimeError(
                        f"助手启动失败，日志：{root / 'opencode.log'}"
                    ) from None
                await asyncio.sleep(0.5)
        reconcile_started = time.monotonic()
        mcp_status = await client._inner.request("GET", "/mcp", directory=client.workspace)
        assert mcp_status.get("nexus-assistant", {}).get("status") == "connected", mcp_status
        await reconcile_task_reviews()
        deadline = time.monotonic() + timeout
        summaries = []
        summaries_found = 0
        while time.monotonic() < deadline:
            async with SessionLocal() as session:
                summaries = (await session.scalars(select(TaskSummary))).all()
            summaries_found = len(summaries)
            if summaries_found == 3:
                break
            await asyncio.sleep(1)
        # 真实经过时间与真实提交数：单调时钟实测，不回填 timestamp。
        summaries_elapsed = round(time.monotonic() - reconcile_started, 3)
        async with SessionLocal() as session:
            items = (await session.scalars(select(KnowledgeItem))).all()
            texts = {s.task_id: s.content_md for s in summaries}
            statuses = (await session.scalars(select(Task.status))).all()
        report = {
            "root": str(root),
            "timeout_budget_seconds": timeout,
            "reconcile_elapsed_seconds": summaries_elapsed,
            "summaries_found": summaries_found,
            "summaries": texts,
            "experiences": [
                {
                    "task_id": i.source_task_id,
                    "status": i.status,
                    "content": i.content_md,
                }
                for i in items
            ],
            "read_counts": {sid: len(ids) for sid, ids in reads.items()},
            "task_statuses": statuses,
        }
        (root / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2)
        )
        assert len(summaries) == 3, f"助手未完成全部结构化提交：{root}"
        assert all(
            len(reads[sid]) == len(messages) for sid, messages in data.items()
        ), "遗漏会话分页"
        assert "删除" in texts["T0"] and "保留" in texts["T0"], "需求总结遗漏人工纠正"
        assert "租户" in texts["T1"] and "缓存" in texts["T1"], (
            "问题总结遗漏 question 补充的根因"
        )
        assert any(i.source_task_id == "T0" for i in items)
        assert any(i.source_task_id == "T1" for i in items)
        assert not any(i.source_task_id == "T2" for i in items), (
            "无经验任务不应生成 candidate"
        )
        # A historical protocol may be recorded as history (with an explicit
        # "no longer required" note), but it must never be promoted to a current
        # rule or a reusable experience.
        assert not any(_promotes_abandoned_protocol(i.content_md) for i in items), (
            "不得将历史输出协议提炼为当前经验"
        )
        assert not _promotes_abandoned_protocol(texts.get("T0", ""))
        assert all(i.status == "candidate" for i in items)
        assert statuses == ["SUCCEEDED"] * 3
        return report
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()
        source.shutdown()
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--opencode", default="opencode")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(run(args.model, args.opencode, args.timeout)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
