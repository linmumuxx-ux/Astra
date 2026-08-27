import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config.settings import get_settings
from app.database import SessionLocal
from app.domain import (
    CompletionPolicy,
    EmployeeStatus,
    ExecutionMode,
    RunStatus,
    TaskStatus,
)
from app.executors.opencode_cli import OpenCodeCLIExecutor
from app.executors.opencode_remote import RemoteOpenCodeExecutor
from app.executors.usage import parse_opencode_usage
from app.models import DigitalEmployee, Evidence, Run, Task, ToolUsage
from app.runtime.environment import (
    ExecutionEnvironmentRuntime,
    environment_from_snapshot,
    environment_snapshot,
)
from app.runtime.result_parser import build_work_result, human_readable_result
from app.services import TaskService
from app.sources.nr_test_system import NrTestSystemSource
from app.structured_logging import runtime_log


class TaskCoordinator:
    """Observe one autonomous OpenCode execution without prescribing its workflow."""

    def __init__(self, *, executor=None, source=None) -> None:
        self.settings = get_settings()
        self.executor = executor
        self.environment_runtime = ExecutionEnvironmentRuntime(self.settings)
        self.source = source or NrTestSystemSource(self.settings)

    async def process(self, task_id: str) -> None:
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            if not task or not task.employee_id or task.status != TaskStatus.RUNNING:
                return
            employee = await session.scalar(
                select(DigitalEmployee)
                .where(DigitalEmployee.id == task.employee_id)
                .options(selectinload(DigitalEmployee.execution_environment))
            )
            if not employee:
                return
            service = TaskService(session)
            try:
                environment = self._resolve_environment(task, employee)
                task.execution_environment_snapshot = (
                    task.execution_environment_snapshot or environment_snapshot(environment)
                )
                workspace = Path(environment.workspace_root).expanduser()
                if environment.mode == ExecutionMode.LOCAL:
                    workspace = workspace.resolve()
                    if not workspace.is_dir():
                        raise RuntimeError(f"员工工作空间不存在: {workspace}")
                task.current_progress = "OpenCode 正在自主处理任务"
                await service.add_event(
                    task,
                    "WORK_STARTED",
                    "work",
                    f"{employee.name} 开始处理任务",
                    {"workspace": str(workspace), "environment": environment.name},
                )
                executor = self.executor or (
                    RemoteOpenCodeExecutor(
                        environment,
                        self.settings,
                        self.environment_runtime,
                        event_callback=lambda event: self._observe_event(task, None, event, service),
                    )
                    if environment.mode == ExecutionMode.LINUX_REMOTE
                    else OpenCodeCLIExecutor(
                        self.settings,
                        opencode_binary=environment.opencode_path,
                        event_callback=lambda event: self._observe_event(task, None, event, service),
                    )
                )
                await self._execute_once(task, employee, environment, workspace, executor, session)
            except Exception as exc:
                runtime_log(
                    logging.ERROR,
                    "任务运行异常",
                    employee_id=employee.id,
                    task_id=task.id,
                    phase="work",
                    error=str(exc),
                )
                await session.refresh(task)
                if task.status == TaskStatus.RUNNING:
                    task.execution_error = {
                        "reason": str(exc),
                        "current_progress": task.current_progress,
                        "environment": task.execution_environment_snapshot,
                        "session_id": task.opencode_session_id,
                        "last_activity_at": (
                            task.last_activity_at.isoformat() if task.last_activity_at else None
                        ),
                        "occurred_at": datetime.now(UTC).isoformat(),
                    }
                    await service.transition(
                        task,
                        TaskStatus.EXECUTION_ERROR,
                        current_progress="执行发生异常，等待恢复",
                        message="任务执行发生异常",
                        detail={"error": str(exc)},
                    )
                employee.status = EmployeeStatus.ERROR
                await session.commit()

    @staticmethod
    def _resolve_environment(task: Task, employee: DigitalEmployee):
        if task.execution_environment_snapshot:
            return environment_from_snapshot(task.execution_environment_snapshot, employee.id)
        if employee.execution_environment:
            return employee.execution_environment
        raise RuntimeError("员工尚未配置 OpenCode 工作环境")

    async def _execute_once(self, task, employee, environment, workspace, executor, session) -> None:
        service = TaskService(session)
        run_number = (await session.scalar(select(func.count(Run.id)).where(Run.task_id == task.id)) or 0) + 1
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
            "work",
            "OpenCode 会话已启动" if run_number == 1 else "OpenCode 会话已继续",
            {"run_number": run_number, "resume_session": bool(task.opencode_session_id)},
            run.id,
        )

        if hasattr(executor, "event_callback"):
            executor.event_callback = lambda event: self._observe_event(task, run, event, service)

        resumed_session = task.opencode_session_id
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
        raw_summary = self._last_text(result.output) or result.stderr.strip()
        summary = human_readable_result(raw_summary) or "OpenCode 执行已结束"
        run.result = {
            "status": result.status,
            "session_id": result.session_id,
            "summary": summary,
            "stderr": result.stderr[-4000:],
            "usage_source": "opencode_json_events",
        }
        evidence_path = self._save_observation(task, run, result)
        session.add(
            Evidence(
                task_id=task.id,
                run_id=run.id,
                name=evidence_path.name,
                kind="work_record",
                path=str(evidence_path),
                size=evidence_path.stat().st_size,
                content_type="application/json",
            )
        )
        await session.commit()
        if task.status != TaskStatus.RUNNING:
            run.status = RunStatus.CANCELLED
            stopped_status = {
                TaskStatus.SUSPENDED: "任务已挂起",
                TaskStatus.CANCELLED: "任务已取消",
            }.get(task.status, "任务已离开处理中状态")
            await service.add_event(
                task,
                "WORK_STOPPED",
                "work",
                f"{stopped_status}，本次 OpenCode 返回结果仅作为工作记录保留",
                {"run_number": run_number, "exit_code": result.exit_code},
                run.id,
            )
            return
        if not getattr(executor, "event_callback", None):
            await self._record_progress_messages(task, run, result.output, service)

        if result.status == "BLOCKED":
            run.status = RunStatus.BLOCKED
            task.human_required_reason = summary
            task.human_intervention = {
                "blocking_reason": summary,
                "completed_work": "详见工作记录与 OpenCode 输出",
                "current_state": task.current_progress,
                "requested_input": "请根据员工说明补充必要信息或权限",
            }
            await service.transition(
                task,
                TaskStatus.WAIT_HUMAN,
                current_progress="已阻塞，等待人工补充信息",
                message=f"{employee.name} 请求人工协助",
                run_id=run.id,
            )
            employee.status = EmployeeStatus.WAIT_HUMAN
            await session.commit()
            return

        if result.exit_code != 0:
            run.status = RunStatus.FAILED
            if resumed_session and self._session_unavailable(result.stderr, result.stdout):
                task.opencode_session_id = None
                task.current_progress = "原 OpenCode 会话不可用，携带现有上下文创建新会话"
                await service.add_event(
                    task,
                    "SESSION_RECOVERY",
                    "work",
                    task.current_progress,
                    {"unavailable_session_id": resumed_session},
                    run.id,
                )
                await self._execute_once(task, employee, environment, workspace, executor, session)
                return
            if run_number <= employee.max_auto_retries:
                task.current_progress = (
                    f"OpenCode 执行异常，正在恢复同一任务会话（{run_number}/{employee.max_auto_retries}）"
                )
                await service.add_event(
                    task,
                    "WORK_RETRY",
                    "work",
                    task.current_progress,
                    {"exit_code": result.exit_code, "run_number": run_number},
                    run.id,
                )
                await session.commit()
                await self._execute_once(task, employee, environment, workspace, executor, session)
                return
            task.execution_error = {
                "reason": result.stderr.strip() or summary,
                "exit_code": result.exit_code,
                "session_id": task.opencode_session_id,
                "current_progress": task.current_progress,
                "last_activity_at": (task.last_activity_at.isoformat() if task.last_activity_at else None),
                "occurred_at": datetime.now(UTC).isoformat(),
            }
            await service.transition(
                task,
                TaskStatus.EXECUTION_ERROR,
                current_progress="执行发生异常，等待恢复",
                message=f"{employee.name} 的执行发生异常",
                detail={"exit_code": result.exit_code},
                run_id=run.id,
            )
            employee.status = EmployeeStatus.ERROR
            await session.commit()
            return

        task.result = build_work_result(
            raw_summary,
            task.acceptance_criteria,
            str(evidence_path),
        )
        task.human_required_reason = None
        run.result = {**run.result, "work_result": task.result}
        run.status = RunStatus.PASSED
        task.submitted_at = datetime.now(UTC)
        requires_confirmation = task.completion_policy == CompletionPolicy.MANUAL_CONFIRM
        await service.transition(
            task,
            TaskStatus.PENDING_CONFIRMATION if requires_confirmation else TaskStatus.COMPLETED,
            current_progress="结果已提交，等待确认" if requires_confirmation else "任务已完成",
            message=(
                f"{employee.name} 提交任务结果，等待确认"
                if requires_confirmation
                else f"{employee.name} 完成任务"
            ),
            run_id=run.id,
        )
        self._release_employee(employee)
        await session.commit()
        await self._backfill_source(task)

    def _save_observation(self, task: Task, run: Run, result) -> Path:
        record_dir = (self.settings.workspace_root / "records" / task.id).resolve()
        record_dir.mkdir(parents=True, exist_ok=True)
        path = record_dir / f"{run.id}-opencode.json"
        path.write_text(
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
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _last_text(events: list[dict]) -> str:
        texts: list[str] = []
        for event in events:
            part = event.get("part", {}) if isinstance(event, dict) else {}
            text = part.get("text") if isinstance(part, dict) else None
            text = text or event.get("text")
            if text:
                texts.append(str(text).strip())
        return texts[-1] if texts else ""

    @staticmethod
    async def _record_progress_messages(
        task: Task,
        run: Run,
        events: list[dict],
        service: TaskService,
    ) -> None:
        messages: list[str] = []
        for event in events:
            if not isinstance(event, dict) or event.get("type") != "text":
                continue
            part = event.get("part", {})
            raw_text = part.get("text") if isinstance(part, dict) else None
            text = human_readable_result(str(raw_text or event.get("text", ""))).strip()
            if text and text not in messages:
                messages.append(text)
        for message in messages[-10:]:
            task.current_progress = message[:500]
            await service.add_event(task, "WORK_PROGRESS", "work", message[:2000], run_id=run.id)

    @staticmethod
    async def _observe_event(task: Task, run: Run | None, event: dict, service: TaskService) -> None:
        if not isinstance(event, dict):
            return
        part = event.get("part") if isinstance(event.get("part"), dict) else event
        event_type = str(event.get("type", part.get("type", ""))).lower()
        run_id = run.id if run else None
        if event_type == "text" or str(part.get("type", "")).lower() == "text":
            message = human_readable_result(str(part.get("text") or event.get("text") or "")).strip()
            if message:
                task.current_progress = message[:500]
                await service.add_event(task, "WORK_PROGRESS", "work", message[:2000], run_id=run_id)
            return
        if "tool" in event_type or "tool" in str(part.get("type", "")).lower():
            tool = str(
                part.get("tool")
                or part.get("toolName")
                or part.get("tool_name")
                or part.get("name")
                or "OpenCode Tool"
            )
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            operation_input = state.get("input") or part.get("input")
            await service.add_event(
                task,
                "TOOL_ACTIVITY",
                "operation",
                f"OpenCode 调用 {tool}",
                {
                    "tool": tool,
                    "status": state.get("status") or part.get("status"),
                    "title": state.get("title") or part.get("title"),
                    "input": operation_input,
                },
                run_id,
            )
            return
        if any(key in event_type for key in ("step", "usage", "token")):
            usage, tools, model_name = parse_opencode_usage([event])
            if run:
                for field in (
                    "input_tokens",
                    "output_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                    "total_tokens",
                    "llm_call_count",
                ):
                    value = getattr(usage, field)
                    if value is not None:
                        setattr(run, field, (getattr(run, field) or 0) + value)
                run.tool_call_count = (run.tool_call_count or 0) + sum(item.call_count for item in tools)
                run.model_name = run.model_name or model_name
            await service.add_event(
                task,
                "MODEL_ACTIVITY",
                "operation",
                "OpenCode 返回模型用量事件",
                {
                    "event": event_type,
                    "total_tokens": usage.total_tokens,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "cache_write_tokens": usage.cache_write_tokens,
                    "tool_calls": sum(item.call_count for item in tools),
                    "model": model_name,
                },
                run_id,
            )

    @staticmethod
    def _session_unavailable(stderr: str, stdout: str) -> bool:
        message = f"{stderr}\n{stdout}".lower()
        return "session" in message and any(
            phrase in message for phrase in ("not found", "unknown", "invalid", "does not exist")
        )

    @staticmethod
    def _release_employee(employee: DigitalEmployee) -> None:
        employee.current_task_count = max(0, employee.current_task_count - 1)
        employee.status = EmployeeStatus.IDLE

    async def _backfill_source(self, task: Task) -> None:
        if task.source != "nr_test_system" or not task.external_task_id:
            return
        try:
            await self.source.update_task(
                task.external_task_id,
                {"astra_task_id": task.id, "status": task.status, "result": task.result},
            )
        except Exception as exc:
            runtime_log(
                logging.WARNING,
                "来源系统结果回填失败",
                task_id=task.id,
                phase="work",
                error=str(exc),
            )
