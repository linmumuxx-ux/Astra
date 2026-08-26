import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config.settings import get_settings
from app.database import SessionLocal
from app.domain import EmployeeStatus, EnvironmentStatus, ExecutionMode, RunStatus, TaskStatus
from app.executors.opencode_cli import OpenCodeCLIExecutor
from app.executors.opencode_remote import RemoteOpenCodeExecutor
from app.models import DigitalEmployee, Evidence, Run, Task, ToolUsage
from app.runtime.environment import (
    ExecutionEnvironmentRuntime,
    environment_from_snapshot,
    environment_snapshot,
)
from app.runtime.remote_verifier import RemoteTaskVerifier
from app.runtime.verifier import TaskVerifier
from app.runtime.workspace import WorkspaceManager
from app.services import TaskService
from app.sources.nr_test_system import NrTestSystemSource
from app.structured_logging import runtime_log


class TaskCoordinator:
    def __init__(self, *, executor=None, verifier=None, workspace_manager=None, source=None) -> None:
        self.settings = get_settings()
        self.workspace_manager = workspace_manager or WorkspaceManager(self.settings)
        self.executor = executor
        self.verifier = verifier
        self.environment_runtime = ExecutionEnvironmentRuntime(self.settings)
        self.source = source or NrTestSystemSource(self.settings)

    async def process(self, task_id: str) -> None:
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            if not task or not task.employee_id:
                return
            employee = await session.scalar(
                select(DigitalEmployee)
                .where(DigitalEmployee.id == task.employee_id)
                .options(selectinload(DigitalEmployee.execution_environment))
            )
            if not employee or task.status not in {TaskStatus.CLAIMED, TaskStatus.RUNNING}:
                return
            service = TaskService(session)
            runtime_log(
                logging.INFO,
                "开始处理任务",
                employee_id=employee.id,
                task_id=task.id,
                phase=task.current_phase,
            )
            try:
                if task.execution_environment_snapshot:
                    environment = environment_from_snapshot(task.execution_environment_snapshot, employee.id)
                elif (
                    employee.execution_environment
                    and employee.execution_environment.status == EnvironmentStatus.AVAILABLE
                ):
                    environment = employee.execution_environment
                    task.execution_environment_snapshot = environment_snapshot(environment)
                else:
                    raise RuntimeError("员工 OpenCode 执行环境不可用或尚未测试")

                is_remote = environment.mode == ExecutionMode.LINUX_REMOTE
                control_workspace = await self.workspace_manager.create(task, copy_source=not is_remote)
                workspace = (
                    await self.environment_runtime.prepare_remote_workspace(task, environment)
                    if is_remote
                    else control_workspace
                )
                task.workspace = str(workspace)
                await service.add_event(
                    task,
                    "WORKSPACE_CREATED",
                    "workspace",
                    "任务独立 Workspace 已就绪",
                    {
                        "workspace": str(workspace),
                        "execution_environment": task.execution_environment_snapshot,
                    },
                )
                if task.status == TaskStatus.CLAIMED:
                    await service.transition(
                        task,
                        TaskStatus.RUNNING,
                        phase="executing",
                        progress=15,
                        message="OpenCode 执行即将开始",
                    )
                executor = self.executor or (
                    RemoteOpenCodeExecutor(environment, self.settings, self.environment_runtime)
                    if is_remote
                    else OpenCodeCLIExecutor(self.settings, opencode_binary=environment.opencode_path)
                )
                await self._run_until_terminal(
                    task,
                    employee,
                    workspace,
                    control_workspace,
                    environment,
                    executor,
                    session,
                )
            except Exception as exc:
                runtime_log(
                    logging.ERROR,
                    "任务运行时异常",
                    employee_id=employee.id,
                    task_id=task.id,
                    phase="runtime_error",
                    error=str(exc),
                )
                await session.refresh(task)
                if task.status in {
                    TaskStatus.CLAIMED,
                    TaskStatus.RUNNING,
                    TaskStatus.VERIFYING,
                    TaskStatus.RETRY,
                }:
                    task.human_required_reason = f"运行时异常: {exc}"
                    await service.transition(
                        task,
                        TaskStatus.WAIT_HUMAN,
                        phase="runtime_error",
                        progress=task.progress,
                        message="运行时异常，需要人工检查",
                        detail={"error": str(exc)},
                    )
                employee.status = EmployeeStatus.WAIT_HUMAN
                await session.commit()

    async def _run_until_terminal(
        self,
        task,
        employee,
        workspace,
        control_workspace,
        environment,
        executor,
        session,
    ) -> None:
        service = TaskService(session)
        while True:
            run_number = (
                await session.scalar(select(func.count(Run.id)).where(Run.task_id == task.id)) or 0
            ) + 1
            run = Run(
                id=f"RUN-{uuid4().hex[:10].upper()}",
                task_id=task.id,
                employee_id=employee.id,
                run_number=run_number,
                status=RunStatus.RUNNING,
                executor_type=(
                    "opencode_ssh"
                    if environment.mode == ExecutionMode.LINUX_REMOTE
                    else self.settings.executor_type
                ),
                opencode_session_id=task.opencode_session_id,
                execution_environment_snapshot=task.execution_environment_snapshot or {},
            )
            session.add(run)
            await session.commit()
            await service.add_event(
                task,
                "OPENCODE_STARTED",
                "executing",
                f"OpenCode Run {run_number} 已启动",
                {"run_number": run_number, "resume_session": bool(task.opencode_session_id)},
                run.id,
            )
            runtime_log(
                logging.INFO,
                f"OpenCode Run {run_number} 已启动",
                employee_id=employee.id,
                task_id=task.id,
                run_id=run.id,
                phase="executing",
            )
            result = (
                await executor.resume(task, run, workspace)
                if task.opencode_session_id
                else await executor.start(task, workspace)
            )
            await session.refresh(task)
            task.opencode_session_id = result.session_id or task.opencode_session_id
            run.opencode_session_id = task.opencode_session_id
            run.exit_code = result.exit_code
            run.model_name = result.model_name or self.settings.opencode_model
            run.input_tokens = result.token_usage.input_tokens
            run.output_tokens = result.token_usage.output_tokens
            run.cache_read_tokens = result.token_usage.cache_read_tokens
            run.cache_write_tokens = result.token_usage.cache_write_tokens
            run.total_tokens = result.token_usage.total_tokens
            run.llm_call_count = result.token_usage.llm_call_count
            run.tool_call_count = (
                sum(item.call_count for item in result.tool_usage) if result.tool_usage else None
            )
            run.result = {
                "status": result.status,
                "session_id": result.session_id,
                "stderr": result.stderr[-4000:],
                "usage_source": "opencode_json_events",
            }
            run.finished_at = datetime.now(UTC)
            session.add_all(
                [
                    ToolUsage(
                        run_id=run.id,
                        tool_name=item.name,
                        call_count=item.call_count,
                        success_count=item.success_count,
                        failure_count=item.failure_count,
                        duration_ms=item.duration_ms,
                    )
                    for item in result.tool_usage
                ]
            )

            output_path = control_workspace / "evidence" / "opencode_output.json"
            output_path.write_text(
                json.dumps(
                    {
                        "status": result.status,
                        "exit_code": result.exit_code,
                        "session_id": result.session_id,
                        "events": result.output,
                        "stderr": result.stderr,
                        "usage": {
                            "model": run.model_name,
                            "input_tokens": run.input_tokens,
                            "output_tokens": run.output_tokens,
                            "cache_read_tokens": run.cache_read_tokens,
                            "cache_write_tokens": run.cache_write_tokens,
                            "total_tokens": run.total_tokens,
                            "llm_call_count": run.llm_call_count,
                            "tool_call_count": run.tool_call_count,
                            "tools": [
                                {
                                    "name": item.name,
                                    "call_count": item.call_count,
                                    "success_count": item.success_count,
                                    "failure_count": item.failure_count,
                                    "duration_ms": item.duration_ms,
                                }
                                for item in result.tool_usage
                            ],
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            await self._add_evidence(session, task, run, output_path, "opencode_output")

            if task.status in {TaskStatus.PAUSED, TaskStatus.CANCELLED, TaskStatus.WAIT_HUMAN}:
                run.status = (
                    RunStatus.CANCELLED
                    if task.status in {TaskStatus.PAUSED, TaskStatus.CANCELLED}
                    else RunStatus.BLOCKED
                )
                await session.commit()
                return

            if result.status == "BLOCKED":
                run.status = RunStatus.BLOCKED
                task.human_required_reason = result.stderr or "OpenCode 返回 BLOCKED"
                await session.commit()
                await service.transition(
                    task,
                    TaskStatus.WAIT_HUMAN,
                    phase="blocked",
                    progress=task.progress,
                    message="OpenCode 无法自主继续，需要人工介入",
                    run_id=run.id,
                )
                employee.status = EmployeeStatus.WAIT_HUMAN
                await session.commit()
                return

            if result.exit_code != 0:
                run.status = RunStatus.FAILED
                await session.commit()
                if not await self._retry_or_handoff(task, employee, service, run.id):
                    employee.status = EmployeeStatus.WAIT_HUMAN
                    await session.commit()
                    return
                continue

            await service.transition(
                task,
                TaskStatus.VERIFYING,
                phase="verifying",
                progress=82,
                message="OpenCode 执行结束，开始独立验证",
                run_id=run.id,
            )
            verifier = self.verifier or (
                RemoteTaskVerifier(
                    environment,
                    self.environment_runtime,
                    control_workspace / "evidence",
                )
                if environment.mode == ExecutionMode.LINUX_REMOTE
                else TaskVerifier()
            )
            verification = await verifier.verify(task, workspace)
            runtime_log(
                logging.INFO if verification.passed else logging.WARNING,
                "独立验证完成",
                employee_id=employee.id,
                task_id=task.id,
                run_id=run.id,
                phase="verifying",
                passed=verification.passed,
            )
            for path in verification.evidence:
                await self._add_evidence(session, task, run, path, "verification")
            run.result = {**(run.result or {}), "verification": verification.as_dict()}
            task.result = verification.as_dict()

            if verification.passed:
                run.status = RunStatus.PASSED
                await session.commit()
                if task.source == "nr_test_system" and task.external_task_id:
                    try:
                        await self.source.update_task(
                            task.external_task_id,
                            {
                                "astra_task_id": task.id,
                                "status": "COMPLETED",
                                "result": task.result,
                                "evidence": [str(path) for path in verification.evidence],
                            },
                        )
                    except Exception as exc:
                        task.human_required_reason = f"结果回填失败: {exc}"
                        await service.transition(
                            task,
                            TaskStatus.WAIT_HUMAN,
                            phase="source_backfill",
                            progress=95,
                            message="验证已通过，但来源系统结果回填失败",
                            detail={"error": str(exc)},
                            run_id=run.id,
                        )
                        employee.status = EmployeeStatus.WAIT_HUMAN
                        await session.commit()
                        return
                await service.transition(
                    task,
                    TaskStatus.COMPLETED,
                    phase="completed",
                    progress=100,
                    message="确定性验证通过，任务完成",
                    run_id=run.id,
                )
                employee.status = EmployeeStatus.IDLE
                employee.current_task_count = max(0, employee.current_task_count - 1)
                await session.commit()
                return

            run.status = RunStatus.FAILED
            await session.commit()
            if not verification.repairable:
                task.human_required_reason = "缺少可程序化验证条件，需要人工补充任务输入"
                await service.transition(
                    task,
                    TaskStatus.WAIT_HUMAN,
                    phase="verification_blocked",
                    progress=task.progress,
                    message="Verifier 无法形成真实完成证据，等待人工补充",
                    run_id=run.id,
                )
                employee.status = EmployeeStatus.WAIT_HUMAN
                await session.commit()
                return
            if not await self._retry_or_handoff(task, employee, service, run.id):
                employee.status = EmployeeStatus.WAIT_HUMAN
                await session.commit()
                return

    async def _retry_or_handoff(
        self, task: Task, employee: DigitalEmployee, service: TaskService, run_id: str
    ) -> bool:
        if not employee.auto_repair:
            task.human_required_reason = "员工工作策略未启用自动修复"
            await service.transition(
                task,
                TaskStatus.WAIT_HUMAN,
                phase="repair_disabled",
                progress=task.progress,
                message="自动修复未启用，等待人工处理",
                run_id=run_id,
            )
            return False
        if task.retry_count >= task.max_retry_count:
            task.human_required_reason = "已达到最大自动修复次数"
            await service.transition(
                task,
                TaskStatus.WAIT_HUMAN,
                phase="retry_exhausted",
                progress=task.progress,
                message="自动修复次数已用尽，等待人工处理",
                run_id=run_id,
            )
            return False
        task.retry_count += 1
        await service.transition(
            task,
            TaskStatus.RETRY,
            phase="fault_analysis",
            progress=55,
            message=f"开始第 {task.retry_count} 次自动修复",
            run_id=run_id,
        )
        await service.transition(
            task,
            TaskStatus.RUNNING,
            phase="repairing",
            progress=62,
            message="恢复原 OpenCode Session 继续修复",
            run_id=run_id,
        )
        return True

    @staticmethod
    async def _add_evidence(session, task: Task, run: Run, path: Path, kind: str) -> None:
        exists = await session.scalar(
            select(Evidence.id).where(Evidence.task_id == task.id, Evidence.path == str(path))
        )
        if exists:
            return
        session.add(
            Evidence(
                task_id=task.id,
                run_id=run.id,
                name=path.name,
                kind=kind,
                path=str(path),
                size=path.stat().st_size if path.exists() else 0,
                content_type="application/json" if path.suffix == ".json" else "text/plain",
            )
        )
        await session.commit()
