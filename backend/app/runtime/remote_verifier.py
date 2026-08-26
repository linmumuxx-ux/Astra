import json
import shlex
from datetime import UTC, datetime
from pathlib import Path

from app.models import OpenCodeExecutionEnvironment, Task
from app.runtime.environment import ExecutionEnvironmentRuntime
from app.runtime.verifier import VerificationItem, VerificationResult


class RemoteTaskVerifier:
    def __init__(
        self,
        environment: OpenCodeExecutionEnvironment,
        runtime: ExecutionEnvironmentRuntime,
        local_evidence_dir: Path,
    ):
        self.environment = environment
        self.runtime = runtime
        self.local_evidence_dir = local_evidence_dir

    async def verify(self, task: Task, workspace: Path) -> VerificationResult:
        config = task.input.get("verification", {})
        source = workspace / "source"
        self.local_evidence_dir.mkdir(parents=True, exist_ok=True)
        items: list[VerificationItem] = []
        evidence: list[Path] = []

        for relative_name in config.get("required_files", []):
            if relative_name.startswith("/") or ".." in Path(relative_name).parts:
                exists, detail = False, "路径越界"
            else:
                candidate = shlex.quote(str(source / relative_name))
                code, _, stderr = await self.runtime.run_remote(
                    self.environment, f"test -f {candidate}", timeout=30
                )
                exists = code == 0
                detail = "文件存在" if exists else (stderr.strip() or "文件不存在")
            items.append(VerificationItem(f"目标文件: {relative_name}", exists, detail))

        command_value = config.get("test_command")
        if not command_value:
            items.append(
                VerificationItem(
                    "真实测试执行",
                    False,
                    "任务未提供 input.verification.test_command，不能程序化证明完成",
                )
            )
            return self._write_report(VerificationResult(False, False, items, evidence))

        command = shlex.split(command_value) if isinstance(command_value, str) else list(command_value)
        if not command or not all(isinstance(item, str) for item in command):
            raise ValueError("verification.test_command must be a command string or string array")
        remote_command = f"cd {shlex.quote(str(source))} && {shlex.join(command)}"
        code, stdout, stderr = await self.runtime.run_remote(
            self.environment,
            remote_command,
            timeout=int(config.get("timeout_seconds", 900)),
        )
        execution_log = self.local_evidence_dir / "execution.log"
        execution_log.write_text(f"{stdout}{stderr}", encoding="utf-8")
        evidence.append(execution_log)
        expected_code = int(config.get("expected_exit_code", 0))
        passed = code == expected_code
        items.append(VerificationItem("真实测试执行", passed, f"退出码 {code}，期望 {expected_code}"))
        test_result = self.local_evidence_dir / "test_result.json"
        test_result.write_text(
            json.dumps(
                {
                    "command": command,
                    "exit_code": code,
                    "expected_exit_code": expected_code,
                    "passed": passed,
                    "execution_mode": "LINUX_REMOTE",
                    "executed_at": datetime.now(UTC).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        evidence.append(test_result)

        for name in ["opencode_output.json", *config.get("required_evidence", [])]:
            candidate = (self.local_evidence_dir / name).resolve()
            safe = self.local_evidence_dir.resolve() in candidate.parents
            exists = safe and candidate.is_file() and candidate.stat().st_size > 0
            items.append(
                VerificationItem(f"验证证据: {name}", exists, "证据有效" if exists else "证据缺失或为空")
            )
            if exists:
                evidence.append(candidate)
        return self._write_report(
            VerificationResult(all(item.passed for item in items), True, items, evidence)
        )

    def _write_report(self, result: VerificationResult) -> VerificationResult:
        report = self.local_evidence_dir / "verify_report.json"
        report.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        result.evidence.append(report)
        return result
