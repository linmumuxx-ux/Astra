"""Backend-owned display contract. No events or timestamps infer runtime state."""

ACTIVE = {"QUEUED", "STARTING", "RUNNING", "WAITING_INPUT"}
LABELS = {
    "READY": "等待领取",
    "ASSIGNED": "已分配",
    "QUEUED": "等待执行",
    "STARTING": "启动中",
    "RUNNING": "执行中",
    "WAITING_INPUT": "等待人工输入",
    "SUSPENDED": "已暂停",
    "PENDING_CONFIRMATION": "等待确认",
    "COMPLETED": "已完成",
    "EXECUTION_ERROR": "执行异常",
    "FAILED": "执行失败",
    "TIMEOUT": "执行超时",
    "LOST": "运行丢失",
    "CANCELLED": "已取消",
    "IDLE": "空闲",
    "OFFLINE": "离线",
    "PAUSED": "已暂停",
    "ERROR": "异常",
    "UNKNOWN": "状态待校正",
}


class RuntimeProjection:
    def _runtime_run(self):
        if self.__tablename__ == "runs":
            return self
        run_id = self.active_run_id
        if not run_id:
            return None
        from sqlalchemy.orm import object_session

        from app.models import Run

        session = object_session(self)
        run = session.identity_map.get((Run, (run_id,), None)) if session else None
        run = run or self.__dict__.get("runtime_run")
        return run if run and run.id == run_id and run.status in ACTIVE else None

    @property
    def runtime_state(self) -> str:
        run = self._runtime_run()
        if run:
            return run.status
        if self.status in {"RUNNING", "QUEUED", "WAIT_HUMAN", "WORKING"}:
            return "UNKNOWN"
        return self.status

    @property
    def runtime_status_label(self) -> str:
        return LABELS.get(self.runtime_state, "状态待校正")

    @property
    def runtime_detail(self) -> str:
        run = self._runtime_run()
        if run and run.executor_status == "ORPHANED_BUSY":
            return "Worker 心跳丢失，Agent 会话仍在运行，正在守望恢复"
        if run and run.executor_status == "PROBE_ERROR":
            return "暂时无法探测 Agent 会话，保留现场并自动重试探测"
        if self.runtime_state == "UNKNOWN":
            return "活动运行指针不一致，等待 Runtime Recovery 校正"
        return getattr(self, "current_progress", "") or ""

    @property
    def active_run(self) -> dict | None:
        run = self._runtime_run()
        if not run or run.status not in ACTIVE:
            return None
        return {
            "id": run.id,
            "status": run.status,
            "trigger_reason": run.trigger_reason,
            "retry_index": run.retry_index,
            "opencode_session_id": run.opencode_session_id,
        }

    @property
    def failure(self) -> dict | None:
        run = self._runtime_run()
        if run and run.failure_code:
            return {
                key: getattr(run, key)
                for key in ("failure_code", "failure_scope", "retryable", "recovery_action", "raw_error")
            }
        error = getattr(self, "execution_error", None)
        return error.get("failure") if error and not run else None
