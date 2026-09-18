"""Task status metadata shared verbatim with the frontend."""
import json
from pathlib import Path

TASK_STATUS = json.loads(Path(__file__).with_name("task_status.json").read_text())
EMPLOYEE_LABELS = {
    "WORKING": "工作中", "WAIT_HUMAN": "等待人工", "IDLE": "空闲", "OFFLINE": "离线",
    "PAUSED": "已暂停", "ERROR": "异常",
}


class RuntimeProjection:
    @property
    def runtime_state(self):
        return self.status

    @property
    def runtime_status_label(self):
        if self.__tablename__ == "tasks":
            return TASK_STATUS[self.status]["label"]
        return EMPLOYEE_LABELS.get(self.status, self.status)

    @property
    def runtime_detail(self):
        return getattr(self, "runtime_error", None) or getattr(self, "current_progress", "") or ""

    @property
    def failure(self):
        error = getattr(self, "failure_reason", None)
        return {"raw_error": error} if error else None
