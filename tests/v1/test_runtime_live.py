"""显式启用的真实 OpenCode 工程验收，只操作独立临时仓库。

ASTRA_LIVE_OPENCODE=1 ASTRA_LIVE_MODEL=provider/model python -m pytest -q -s tests/v1/test_runtime_live.py
不属于完整 Astra 系统验收；消耗真实模型额度，默认跳过。
"""

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest

from domains.runtime import OpenCodeClient, OpenCodeConfig, RuntimePurpose
from domains.runtime.errors import OpenCodeEventStreamInterrupted
from domains.runtime.workspace import prepare_task_workspace, verify_workspace_binding

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("ASTRA_LIVE_OPENCODE") != "1",
        reason="真实模型验收须显式设置 ASTRA_LIVE_OPENCODE=1",
    ),
]

_TESTS = """import unittest
from arithmetic import add

class AdditionContract(unittest.TestCase):
    def test_positive(self): self.assertEqual(add(2, 3), 5)
    def test_negative(self): self.assertEqual(add(-7, 2), -5)
    def test_zero(self): self.assertEqual(add(0, 0), 0)
    def test_large(self): self.assertEqual(add(10**50, 10**50), 2*10**50)
    def test_reject_non_integers(self):
        for value in (True, False, 1.2, "2", None, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(TypeError): add(value, 1)
                with self.assertRaises(TypeError): add(1, value)

if __name__ == "__main__": unittest.main()
"""


async def run_command(directory, *args):
    process = await asyncio.create_subprocess_exec(
        *args, cwd=str(directory), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await process.communicate()
    return process.returncode, out.decode(errors="replace"), err.decode(errors="replace")


async def test_real_task_native_session_tool_evidence_and_workspace_recovery(tmp_path):
    model = os.environ["ASTRA_LIVE_MODEL"]
    preserved_root = os.getenv("ASTRA_LIVE_WORK_ROOT")
    physical = (Path(preserved_root).resolve() / uuid4().hex) if preserved_root else tmp_path.resolve()
    physical.mkdir(parents=True, exist_ok=True)
    repository, storage = physical / "project", physical / "workspaces"
    repository.mkdir()
    storage.mkdir()
    (repository / "test_arithmetic.py").write_text(_TESTS)
    test_digest = hashlib.sha256(_TESTS.encode()).hexdigest()
    for args in [
        ("init", "-q"),
        ("add", "."),
        (
            "-c",
            "user.name=Astra Live Test",
            "-c",
            "user.email=runtime@example.invalid",
            "commit",
            "-qm",
            "acceptance baseline",
        ),
    ]:
        code, _, _ = await run_command(repository, "git", *args)
        assert code == 0
    workspace = await prepare_task_workspace(
        project_root=str(repository),
        workspace_root=str(storage),
        task_id="runtime-live-task",
        execution_id=str(uuid4()),
    )
    config = OpenCodeConfig(
        os.getenv("ASTRA_LIVE_URL", "http://127.0.0.1:4096"),
        "runtime-live-verification",
        RuntimePurpose.TASK,
        (str(storage),),
        model=model,
        username=os.getenv("ASTRA_LIVE_USERNAME", "opencode"),
        password=os.getenv("ASTRA_LIVE_PASSWORD"),
    )
    api = OpenCodeClient(config)
    report_path = Path(os.getenv("ASTRA_LIVE_REPORT", str(physical / "runtime-live-report.json")))
    report = {
        "kind": "real_opencode_engineering_probe",
        "model": model,
        "result": "FAILED",
        "workspace": workspace.directory,
        "started_at": time.time(),
        "whole_system_acceptance": False,
    }
    binding, reader = None, None
    events = []
    try:
        report["health"] = await api.verify_contract()
        binding = await api.create_session(
            workspace.directory,
            owner_ref=workspace.execution_id,
            title="Astra 1.0 isolated runtime acceptance",
            permission_rules=[
                {"permission": "*", "pattern": "*", "action": "deny"},
                *(
                    {"permission": tool, "pattern": "*", "action": "allow"}
                    for tool in ["read", "glob", "grep", "list", "edit"]
                ),
                {"permission": "edit", "pattern": "*test_arithmetic.py", "action": "deny"},
                {"permission": "bash", "pattern": "python3 -m unittest -v", "action": "allow"},
            ],
        )
        report["native_session_id"] = binding.native_session_id

        async def observe():
            try:
                async for event in api.events(binding):
                    events.append({"id": event.get("id"), "type": event["type"]})
            except OpenCodeEventStreamInterrupted:
                report["event_stream_interrupted"] = True

        reader = asyncio.create_task(observe())
        await asyncio.sleep(0.2)
        await api.prompt_async(
            binding,
            message_id="msg" + uuid4().hex,
            text=(
                "In this isolated workspace create arithmetic.py, defining add(a, b). Accept only int values "
                "excluding bool; raise TypeError for any invalid argument; otherwise return a + b. "
                "Read test_arithmetic.py; do not modify it. Use your file edit tool, then run the exact "
                "command python3 -m unittest -v. Do not use network or install packages. "
                "Do not change other files. "
                "Finish with a concise result grounded in the actual tool output."
            ),
        )
        deadline = time.monotonic() + int(os.getenv("ASTRA_LIVE_TIMEOUT", "180"))
        messages = []
        while time.monotonic() < deadline:
            page = await api.messages(binding)
            messages = page["messages"]
            errors = [message for message in messages if message.get("info", {}).get("error")]
            if errors:
                raise AssertionError("原生模型消息含执行错误；未通过真实验收")
            finished = any(
                message.get("info", {}).get("role") == "assistant"
                and message.get("info", {}).get("finish") in {"stop", "end_turn"}
                for message in messages
            )
            if finished and (await api.status(binding))["type"] == "idle":
                break
            await asyncio.sleep(1)
        else:
            raise AssertionError("真实模型执行未在预算时间内给出原生最终回复")
        tools = [
            part for message in messages for part in message.get("parts", []) if part.get("type") == "tool"
        ]
        completed = [part for part in tools if part.get("state", {}).get("status") == "completed"]
        assert any(part.get("tool") in {"edit", "write", "apply_patch"} for part in completed), (
            "缺少原生文件修改证据"
        )
        assert any(
            part.get("tool") == "bash"
            and "python3 -m unittest -v" in json.dumps(part.get("state", {}).get("input", {}))
            for part in completed
        ), "缺少原生测试工具证据"
        output = Path(workspace.directory) / "arithmetic.py"
        assert output.is_file(), "任务没有真实文件产物"
        assert (
            hashlib.sha256(Path(workspace.directory, "test_arithmetic.py").read_bytes()).hexdigest()
            == test_digest
        )
        code, stdout, stderr = await run_command(workspace.directory, "python3", "-m", "unittest", "-v")
        assert code == 0, "独立复验失败"
        await verify_workspace_binding(workspace, workspace_root=str(storage))
        restored = await api.session(binding)
        assert restored["id"] == binding.native_session_id
        report.update(
            {
                "result": "PASSED",
                "tool_evidence": [
                    {
                        "part_id": part.get("id"),
                        "message_id": part.get("messageID"),
                        "tool": part.get("tool"),
                        "state": part.get("state", {}).get("status"),
                    }
                    for part in completed
                ],
                "event_count": len(events),
                "event_types": sorted({event["type"] for event in events}),
                "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "acceptance_test_sha256": test_digest,
                "independent_test_exit_code": code,
                "independent_test_output": stdout + stderr,
                "session_restore_verified": True,
                "workspace_restore_verified": True,
            }
        )
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
        # 原生响应/提示词可能含凭据；不把异常原文持久化到报告。
        raise
    finally:
        if reader:
            reader.cancel()
            try:
                await reader
            except asyncio.CancelledError:
                pass
        if binding:
            report["abort_receipt"] = await api.abort(binding)
        report["finished_at"] = time.time()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(f"真实 Runtime 报告：{report_path}")
