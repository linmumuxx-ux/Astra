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
from app.executors.opencode_remote_server import RemoteOpenCodeServerExecutor
from app.executors.opencode_server import OpenCodeServerExecutor
from app.executors.process import terminate_process
from app.executors.usage import parse_opencode_usage
from app.models import DigitalEmployee, Evidence, Run, SessionMessage, Task, ToolUsage
from app.runtime.environment import (
    ExecutionEnvironmentRuntime,
    environment_from_snapshot,
    environment_snapshot,
)
from app.runtime.result_parser import build_work_result, human_readable_result, parse_human_intervention
from app.runtime.semantic_events import adapt_open_code_events, extract_agent_text
from app.services import TaskService, WorkbenchService, ensure_task_session
from app.sources.nr_test_system import NrTestSystemSource
from app.structured_logging import runtime_log


class TaskCoordinator:
    """Observe one autonomous Agent execution without prescribing its workflow."""

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
                    workspace = self.settings.employee_workspace_path(environment.workspace_root)
                    if not workspace.is_dir():
                        raise RuntimeError(f"员工工作空间不存在: {workspace}")
                task.current_progress = "Agent 正在自主处理任务"
                await service.add_event(
                    task,
                    "WORK_STARTED",
                    "work",
                    f"{employee.name} 开始处理任务",
                    {"workspace": str(workspace), "environment": environment.name},
                )
                executor = self.executor or self._executor_for_environment(
                    task,
                    environment,
                    service,
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
                elif task.status in {TaskStatus.CANCELLED, TaskStatus.SUSPENDED}:
                    self._release_employee(employee)
                await session.commit()

    @staticmethod
    def _resolve_environment(task: Task, employee: DigitalEmployee):
        if task.execution_environment_snapshot:
            environment = environment_from_snapshot(task.execution_environment_snapshot, employee.id)
            # Tasks claimed before employee-level model configuration was added do not
            # have a model in their immutable snapshot. Let those tasks inherit the
            # employee's current model once; new tasks already carry it in the snapshot.
            if not environment.model_name and employee.execution_environment:
                environment.model_name = employee.execution_environment.model_name
            if (
                "opencode_server_port" not in task.execution_environment_snapshot
                and employee.execution_environment
            ):
                environment.opencode_server_port = (
                    employee.execution_environment.opencode_server_port
                )
            # Passwords never enter immutable task/run snapshots. Resolve the
            # current employee secret only at execution time.
            if employee.execution_environment:
                environment.ssh_password = employee.execution_environment.ssh_password
            return environment
        if employee.execution_environment:
            return employee.execution_environment
        raise RuntimeError("员工尚未配置 Agent 工作环境")

    def _executor_for_environment(self, task: Task, environment, service: TaskService):
        async def observe(event):
            await self._observe_event(task, None, event, service)

        if environment.mode == ExecutionMode.LINUX_REMOTE:
            if self.settings.executor_type == "opencode_server":
                return RemoteOpenCodeServerExecutor(
                    environment,
                    self.settings,
                    self.environment_runtime,
                    event_callback=observe,
                )
            return RemoteOpenCodeExecutor(
                environment,
                self.settings,
                self.environment_runtime,
                event_callback=observe,
            )
        if self.settings.executor_type == "opencode_cli_fallback":
            return OpenCodeCLIExecutor(
                self.settings,
                opencode_binary=environment.opencode_path,
                model_name=environment.model_name,
                event_callback=observe,
            )
        return OpenCodeServerExecutor(
            self.settings,
            model_name=environment.model_name,
            event_callback=observe,
        )

    async def _execute_once(self, task, employee, environment, workspace, executor, session) -> None:
        service = TaskService(session)
        work_session = await ensure_task_session(session, task)
        waiting_run = (
            await session.get(Run, work_session.current_run_id) if work_session.current_run_id else None
        )
        resumed_waiting_run = bool(
            waiting_run and waiting_run.status in {RunStatus.WAITING_INPUT, RunStatus.BLOCKED}
        )
        if resumed_waiting_run and waiting_run:
            run = waiting_run
            run.status = RunStatus.RUNNING
            run.finished_at = None
        else:
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
                    (
                        "opencode_server_ssh"
                        if self.settings.executor_type == "opencode_server"
                        else "opencode_cli_fallback_ssh"
                    )
                    if environment.mode == ExecutionMode.LINUX_REMOTE
                    else self.settings.executor_type
                ),
                opencode_session_id=task.opencode_session_id,
                execution_environment_snapshot=task.execution_environment_snapshot or {},
            )
            session.add(run)
        run_number = run.run_number
        work_session.current_run_id = run.id
        work_session.status = "ACTIVE"
        observation_index = (
            await session.scalar(
                select(func.count(Evidence.id)).where(
                    Evidence.run_id == run.id,
                    Evidence.kind == "work_record",
                )
            )
            or 0
        ) + 1
        prior_usage = {
            field: getattr(run, field) or 0
            for field in (
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
                "total_tokens",
                "llm_call_count",
                "tool_call_count",
            )
        }
        pending_messages = (
            (
                await session.execute(
                    select(SessionMessage)
                    .where(
                        SessionMessage.session_id == work_session.id,
                        SessionMessage.status.in_(["PENDING", "QUEUED"]),
                    )
                    .order_by(SessionMessage.created_at)
                )
            )
            .scalars()
            .all()
        )
        if pending_messages:
            instruction = "\n".join(message.content for message in pending_messages)
            task.human_intervention = {
                **(task.human_intervention or {}),
                "response": instruction,
                "responded_at": datetime.now(UTC).isoformat(),
            }
            for message in pending_messages:
                message.run_id = run.id
                message.status = "APPLIED"
        await session.commit()
        await service.add_event(
            task,
            "OPENCODE_STARTED",
            "work",
            "Agent 会话已继续" if task.opencode_session_id else "Agent 会话已启动",
            {
                "run_number": run_number,
                "resume_session": bool(task.opencode_session_id),
                "resume_waiting_run": resumed_waiting_run,
            },
            run.id,
        )

        if hasattr(executor, "event_callback"):
            executor.event_callback = lambda event: self._observe_event(task, run, event, service)
        if hasattr(executor, "session_callback"):
            executor.session_callback = lambda session_id: self._bind_runtime_session(
                task,
                run,
                session_id,
                service,
            )

        resumed_session = task.opencode_session_id
        try:
            result = (
                await executor.resume(task, run, workspace)
                if task.opencode_session_id
                else await executor.start(task, workspace)
            )
        except Exception as exc:
            await self._terminate_executor_processes(executor, run)
            await session.refresh(task)
            await session.refresh(run)
            stopped = task.status in {TaskStatus.CANCELLED, TaskStatus.SUSPENDED}
            run.status = RunStatus.CANCELLED if stopped else RunStatus.FAILED
            run.finished_at = datetime.now(UTC)
            run.result = {
                "status": "CANCELLED" if stopped else "FAILED",
                "session_id": task.opencode_session_id,
                "summary": "任务停止后 Agent 执行已结束" if stopped else "Agent 执行过程中抛出异常",
                "stderr": str(exc),
                "usage_source": "exception",
            }
            await session.commit()
            raise
        await session.refresh(task)
        task.opencode_session_id = result.session_id or task.opencode_session_id
        run.opencode_session_id = task.opencode_session_id
        run.exit_code = result.exit_code
        run.model_name = result.model_name or environment.model_name or self.settings.opencode_model
        for field in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "total_tokens",
            "llm_call_count",
        ):
            value = getattr(result.token_usage, field)
            setattr(
                run, field, prior_usage[field] + value if value is not None else prior_usage[field] or None
            )
        segment_tool_calls = sum(item.call_count for item in result.tool_usage)
        run.tool_call_count = prior_usage["tool_call_count"] + segment_tool_calls or None
        run.finished_at = datetime.now(UTC)
        for item in result.tool_usage:
            usage = await session.scalar(
                select(ToolUsage).where(
                    ToolUsage.run_id == run.id,
                    ToolUsage.tool_name == item.name,
                )
            )
            if usage:
                usage.call_count += item.call_count
                usage.success_count += item.success_count
                usage.failure_count += item.failure_count
                usage.duration_ms += item.duration_ms
            else:
                session.add(
                    ToolUsage(
                        run_id=run.id,
                        tool_name=item.name,
                        call_count=item.call_count,
                        success_count=item.success_count,
                        failure_count=item.failure_count,
                        duration_ms=item.duration_ms,
                    )
                )
        raw_summary = self._last_text(result.output) or result.stderr.strip()
        summary = human_readable_result(raw_summary) or "Agent 执行已结束"
        segment_result = {
            "status": result.status,
            "session_id": result.session_id,
            "summary": summary,
            "stderr": result.stderr[-4000:],
            "usage_source": (
                "opencode_server_events"
                if run.executor_type.startswith("opencode_server")
                else "opencode_cli_json_events"
            ),
        }
        previous_segments = (run.result or {}).get("segments", []) if run.result else []
        run.result = {**segment_result, "segments": [*previous_segments, segment_result]}
        evidence_path = self._save_observation(task, run, result, observation_index)
        evidence = Evidence(
            task_id=task.id,
            run_id=run.id,
            name=evidence_path.name,
            kind="work_record",
            path=str(evidence_path),
            size=evidence_path.stat().st_size,
            content_type="application/json",
        )
        session.add(evidence)
        await session.flush()
        await service.add_event(
            task,
            "ARTIFACT_CREATED",
            "artifact",
            f"已保存工作记录 {evidence.name}",
            {"evidence_id": evidence.id, "name": evidence.name, "path": evidence.path},
            run.id,
        )
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
                f"{stopped_status}，本次 Agent 返回结果仅作为工作记录保留",
                {"run_number": run_number, "exit_code": result.exit_code},
                run.id,
            )
            if task.status in {TaskStatus.CANCELLED, TaskStatus.SUSPENDED}:
                self._release_employee(employee)
            await session.commit()
            return
        if not getattr(executor, "event_callback", None):
            await self._record_progress_messages(task, run, result.output, service)

        if result.status == "BLOCKED":
            run.status = RunStatus.WAITING_INPUT
            run.finished_at = None
            intervention = (
                result.inquiry
                or parse_human_intervention(raw_summary)
                or {
                    "blocking_reason": summary,
                    "completed_work": "详见工作记录与 Agent 输出",
                    "current_state": task.current_progress,
                    "requested_input": "请根据员工说明补充必要信息或权限",
                    "options": [],
                }
            )
            task.human_required_reason = intervention["blocking_reason"]
            task.human_intervention = intervention
            await WorkbenchService(session).create_inquiry(
                task,
                question=intervention["requested_input"],
                description=intervention["blocking_reason"],
                options=intervention.get("options") or [],
                agent_name=employee.id,
                run_id=run.id,
                commit=False,
            )
            await service.transition(
                task,
                TaskStatus.WAIT_HUMAN,
                current_progress=f"等待回复：{intervention['requested_input']}",
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
                task.current_progress = "原 Agent 会话不可用，携带现有上下文创建新会话"
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
                    f"Agent 执行异常，正在恢复同一任务会话（{run_number}/{employee.max_auto_retries}）"
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

        pending_messages = (
            (
                await session.execute(
                    select(SessionMessage)
                    .where(
                        SessionMessage.session_id == work_session.id,
                        SessionMessage.status.in_(["PENDING", "QUEUED"]),
                    )
                    .order_by(SessionMessage.created_at)
                )
            )
            .scalars()
            .all()
        )
        if pending_messages:
            instruction = "\n".join(message.content for message in pending_messages)
            task.human_intervention = {
                **(task.human_intervention or {}),
                "response": instruction,
                "responded_at": datetime.now(UTC).isoformat(),
            }
            task.current_progress = "已完成当前操作，正在应用用户最新指令"
            await service.add_event(
                task,
                "MESSAGE_QUEUED",
                "message",
                "已收到你的指令，将在下一次运行中生效",
                {"message_ids": [message.id for message in pending_messages]},
                run.id,
            )
            run.status = RunStatus.COMPLETED
            await session.commit()
            await self._execute_once(task, employee, environment, workspace, executor, session)
            return

        task.result = build_work_result(
            raw_summary,
            task.acceptance_criteria,
            str(evidence_path),
        )
        task.human_required_reason = None
        run.result = {**run.result, "work_result": task.result}
        run.status = RunStatus.COMPLETED
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

    def _save_observation(self, task: Task, run: Run, result, observation_index: int = 1) -> Path:
        record_dir = self.settings.resolved_workspace_root / "records" / task.id
        record_dir.mkdir(parents=True, exist_ok=True)
        suffix = "" if observation_index == 1 else f"-resume-{observation_index}"
        path = record_dir / f"{run.id}{suffix}-agent.json"
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
            text = extract_agent_text(event) if isinstance(event, dict) else ""
            if text:
                texts.append(str(text).strip())
        return texts[-1] if texts else ""

    @staticmethod
    async def _bind_runtime_session(
        task: Task,
        run: Run,
        session_id: str,
        service: TaskService,
    ) -> None:
        if task.opencode_session_id == session_id and run.opencode_session_id == session_id:
            return
        task.opencode_session_id = session_id
        run.opencode_session_id = session_id
        await service.add_event(
            task,
            "OPENCODE_SESSION_BOUND",
            "metadata",
            "OpenCode Session 已绑定",
            {"session_id": session_id, "runtime": run.executor_type},
            run.id,
        )

    @staticmethod
    async def _record_progress_messages(
        task: Task,
        run: Run,
        events: list[dict],
        service: TaskService,
    ) -> None:
        messages: list[str] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            text = human_readable_result(extract_agent_text(event)).strip()
            if text and text not in messages:
                messages.append(text)
        for message in messages[-10:]:
            task.current_progress = message[:500]
            await WorkbenchService(service.session).add_message(
                task,
                message[:2000],
                role="agent",
                status="APPLIED",
                run_id=run.id,
            )

    @staticmethod
    async def _observe_event(task: Task, run: Run | None, event: dict, service: TaskService) -> None:
        if not isinstance(event, dict):
            return
        run_id = run.id if run else None
        for semantic in adapt_open_code_events(event):
            if semantic.event_type == "message.agent":
                message = human_readable_result(semantic.summary).strip()
                if message:
                    task.current_progress = message[:500]
                    await WorkbenchService(service.session).add_message(
                        task,
                        message[:2000],
                        role="agent",
                        status="APPLIED",
                        run_id=run_id,
                    )
                continue
            if semantic.event_type == "inquiry.requested":
                task.current_progress = f"等待回复：{semantic.summary}"[:500]
                await WorkbenchService(service.session).add_message(
                    task,
                    semantic.summary[:2000],
                    role="agent",
                    status="APPLIED",
                    run_id=run_id,
                )
                continue
            if semantic.event_type.startswith(("agent.", "subagent.")):
                prefix, status = semantic.event_type.split(".", 1)
                await service.add_event(
                    task,
                    f"{prefix.upper()}_{status.upper()}",
                    "agent",
                    semantic.summary,
                    {
                        **semantic.payload,
                        "agent_name": semantic.agent_name,
                    },
                    run_id,
                )
                continue
            if semantic.event_type.startswith("tool."):
                await service.add_event(
                    task,
                    "TOOL_ACTIVITY",
                    "operation",
                    semantic.summary,
                    {
                        **semantic.payload,
                        "semantic_event_type": semantic.event_type,
                        "agent_name": semantic.agent_name,
                    },
                    run_id,
                )
                continue
            if semantic.event_type.startswith("artifact."):
                await service.add_event(
                    task,
                    "ARTIFACT_CREATED" if semantic.event_type.endswith("created") else "ARTIFACT_UPDATED",
                    "artifact",
                    semantic.summary,
                    semantic.payload,
                    run_id,
                )
                continue
            if semantic.event_type == "runtime.metadata":
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
                    "RUNTIME_METADATA",
                    "metadata",
                    semantic.summary,
                    {
                        **semantic.payload,
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
                continue
            if semantic.event_type.startswith("runtime."):
                runtime_kind = semantic.event_type.removeprefix("runtime.").upper()
                await service.add_event(
                    task,
                    f"RUNTIME_{runtime_kind}",
                    "metadata" if semantic.event_type != "runtime.error" else "error",
                    semantic.summary,
                    semantic.payload,
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

    @staticmethod
    async def _terminate_executor_processes(executor, run: Run) -> None:
        abort = getattr(executor, "abort", None)
        if abort:
            try:
                await abort(run)
            except Exception:
                pass
        processes = list(getattr(executor, "_processes", {}).values())
        terminate = getattr(executor, "_terminate_process", None)
        for process in processes:
            try:
                if terminate:
                    await terminate(process)
                else:
                    await terminate_process(process)
            except Exception:
                # The original execution exception remains the useful failure.
                pass

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
