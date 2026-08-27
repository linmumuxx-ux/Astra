from app.domain import TaskStatus


class InvalidTransition(ValueError):
    pass


class TaskStateMachine:
    transitions: dict[TaskStatus, set[TaskStatus]] = {
        TaskStatus.READY: {TaskStatus.RUNNING, TaskStatus.SUSPENDED, TaskStatus.CANCELLED},
        TaskStatus.RUNNING: {
            TaskStatus.COMPLETED,
            TaskStatus.PENDING_CONFIRMATION,
            TaskStatus.WAIT_HUMAN,
            TaskStatus.SUSPENDED,
            TaskStatus.FAILED,
            TaskStatus.EXECUTION_ERROR,
            TaskStatus.CANCELLED,
        },
        TaskStatus.WAIT_HUMAN: {
            TaskStatus.READY,
            TaskStatus.RUNNING,
            TaskStatus.SUSPENDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.SUSPENDED: {TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.CANCELLED},
        TaskStatus.PENDING_CONFIRMATION: {
            TaskStatus.COMPLETED,
            TaskStatus.READY,
            TaskStatus.RUNNING,
            TaskStatus.CANCELLED,
        },
        TaskStatus.EXECUTION_ERROR: {
            TaskStatus.RUNNING,
            TaskStatus.SUSPENDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.COMPLETED: set(),
        TaskStatus.FAILED: set(),
        TaskStatus.CANCELLED: set(),
    }

    @classmethod
    def validate(cls, current: str | TaskStatus, target: str | TaskStatus) -> None:
        current_status = TaskStatus(current)
        target_status = TaskStatus(target)
        if target_status not in cls.transitions[current_status]:
            raise InvalidTransition(f"不允许从 {current_status} 流转到 {target_status}")
