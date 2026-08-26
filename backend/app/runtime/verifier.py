import asyncio
import json
import shlex
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import Task


@dataclass(slots=True)
class VerificationItem:
    name: str
    passed: bool
    detail: str


@dataclass(slots=True)
class VerificationResult:
    passed: bool
    repairable: bool
    items: list[VerificationItem] = field(default_factory=list)
    evidence: list[Path] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "repairable": self.repairable,
            "items": [
                {"name": item.name, "passed": item.passed, "detail": item.detail} for item in self.items
            ],
            "evidence": [str(path) for path in self.evidence],
            "verified_at": datetime.now(UTC).isoformat(),
        }


class TaskVerifier:
    async def verify(self, task: Task, workspace: Path) -> VerificationResult:
        config = task.input.get("verification", {})
        source = (workspace / "source").resolve()
        evidence_dir = workspace / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        items: list[VerificationItem] = []
        evidence: list[Path] = []

        for relative_name in config.get("required_files", []):
            candidate = (source / relative_name).resolve()
            safe = source == candidate or source in candidate.parents
            exists = safe and candidate.is_file()
            items.append(
                VerificationItem(
                    name=f"目标文件: {relative_name}",
                    passed=exists,
                    detail="文件存在" if exists else "文件不存在或路径越界",
                )
            )

        command_value = config.get("test_command")
        if not command_value:
            items.append(
                VerificationItem(
                    name="真实测试执行",
                    passed=False,
                    detail="任务未提供 input.verification.test_command，不能程序化证明完成",
                )
            )
            result = VerificationResult(False, False, items, evidence)
            report = evidence_dir / "verify_report.json"
            report.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            result.evidence.append(report)
            return result

        command = shlex.split(command_value) if isinstance(command_value, str) else list(command_value)
        if not command or not all(isinstance(item, str) for item in command):
            raise ValueError("verification.test_command must be a command string or string array")
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=source,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await asyncio.wait_for(
                process.communicate(), timeout=int(config.get("timeout_seconds", 900))
            )
            exit_code = process.returncode or 0
        except TimeoutError:
            process.kill()
            await process.wait()
            output = b"Verification command timed out"
            exit_code = 124

        execution_log = evidence_dir / "execution.log"
        execution_log.write_bytes(output)
        evidence.append(execution_log)
        expected_code = int(config.get("expected_exit_code", 0))
        execution_passed = exit_code == expected_code
        items.append(
            VerificationItem(
                name="真实测试执行",
                passed=execution_passed,
                detail=f"退出码 {exit_code}，期望 {expected_code}",
            )
        )
        result_payload = {
            "command": command,
            "exit_code": exit_code,
            "expected_exit_code": expected_code,
            "passed": execution_passed,
            "executed_at": datetime.now(UTC).isoformat(),
        }
        test_result = evidence_dir / "test_result.json"
        test_result.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        evidence.append(test_result)

        required_evidence = ["opencode_output.json", *config.get("required_evidence", [])]
        for name in required_evidence:
            candidate = (evidence_dir / name).resolve()
            safe = evidence_dir.resolve() in candidate.parents
            exists = safe and candidate.is_file() and candidate.stat().st_size > 0
            items.append(
                VerificationItem(
                    name=f"验证证据: {name}",
                    passed=exists,
                    detail="证据有效" if exists else "证据缺失或为空",
                )
            )
            if exists:
                evidence.append(candidate)

        result = VerificationResult(all(item.passed for item in items), True, items, evidence)
        report = evidence_dir / "verify_report.json"
        report.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        result.evidence.append(report)
        return result
