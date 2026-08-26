import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select

from app.config.settings import get_settings
from app.database import SessionLocal
from app.domain import EmployeeStatus, RunStatus, TaskStatus
from app.executors.opencode_cli import OpenCodeCLIExecutor
from app.models import DigitalEmployee, Evidence, Run, Task
from app.runtime.verifier import TaskVerifier
from app.runtime.workspace import WorkspaceManager
from app.services import TaskService
from app.sources.nr_test_system import NrTestSystemSource
from app.structured_logging import runtime_log


class TaskCoordinator:
    def __init__(self, *, executor=None, verifier=None, workspace_manager=None, source=None) -> None:
        self.settings = get_settings()
        self.workspace_manager = workspace_manager or WorkspaceManager(self.settings)
        self.executor = executor or OpenCodeCLIExecutor(self.settings)
        self.verifier = verifier or TaskVerifier()
        self.source = source or NrTestSystemSource(self.settings)

    async def process(self, task_id: str) -> None:
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            if not task or not task.employee_id:
                return
            employee = await session.get(DigitalEmployee, task.employee_id)
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
                workspace = (
                    Path(task.workspace)
                    if task.workspace
                    else await self.workspace_manager.create(task)
                )
                task.workspace = str(workspace)
                await service.add_event(
                    task,
                    "WORKSPACE_CREATED",
                    "workspace",
                    "任务独立 Workspace 已就绪",
                    {"workspace": str(workspace)},
                )
                if task.status == TaskStatus.CLAIMED:
                    await service.transition(
                        task,
                        TaskStatus.RUNNING,
                        phase="executing",
                        progress=15,
                        message="OpenCode 执行即将开始",
                    )
                await self._run_until_terminal(task, employee, workspace, session)
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

    async def _run_until_terminal(self, task, employee, workspace, session) -> None:
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
                executor_type=self.settings.executor_type,
                opencode_session_id=task.opencode_session_id,
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
                await self.executor.resume(task, run, workspace)
                if task.opencode_session_id
                else await self.executor.start(task, workspace)
            )
            await session.refresh(task)
            if task.status in {TaskStatus.PAUSED, TaskStatus.CANCELLED, TaskStatus.WAIT_HUMAN}:
                run.status = (
                    RunStatus.CANCELLED
                    if task.status in {TaskStatus.PAUSED, TaskStatus.CANCELLED}
                    else RunStatus.BLOCKED
                )
                run.finished_at = datetime.now(UTC)
                await session.commit()
                return
            task.opencode_session_id = result.session_id or task.opencode_session_id
            run.opencode_session_id = task.opencode_session_id
            run.exit_code = result.exit_code
            run.result = {
                "status": result.status,
                "session_id": result.session_id,
                "stderr": result.stderr[-4000:],
            }
            run.finished_at = datetime.now(UTC)

            output_path = workspace / "evidence" / "opencode_output.json"
            output_path.write_text(
                json.dumps(
                    {
                        "status": result.status,
                        "exit_code": result.exit_code,
                        "session_id": result.session_id,
                        "events": result.output,
                        "stderr": result.stderr,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            await self._add_evidence(session, task, run, output_path, "opencode_output")

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
                if not await self._retry_or_handoff(task, service, run.id):
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
            verification = await self.verifier.verify(task, workspace)
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
            if not await self._retry_or_handoff(task, service, run.id):
                employee.status = EmployeeStatus.WAIT_HUMAN
                await session.commit()
                return

    async def _retry_or_handoff(self, task: Task, service: TaskService, run_id: str) -> bool:
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
