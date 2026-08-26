from app.domain import TaskStatus


class InvalidTransition(ValueError):
    pass


class TaskStateMachine:
    transitions: dict[TaskStatus, set[TaskStatus]] = {
        TaskStatus.CREATED: {TaskStatus.READY, TaskStatus.CANCELLED},
        TaskStatus.READY: {TaskStatus.CLAIMED, TaskStatus.PAUSED, TaskStatus.CANCELLED},
        TaskStatus.CLAIMED: {
            TaskStatus.RUNNING,
            TaskStatus.PAUSED,
            TaskStatus.WAIT_HUMAN,
            TaskStatus.CANCELLED,
        },
        TaskStatus.RUNNING: {
            TaskStatus.VERIFYING,
            TaskStatus.RETRY,
            TaskStatus.WAIT_HUMAN,
            TaskStatus.PAUSED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.VERIFYING: {
            TaskStatus.COMPLETED,
            TaskStatus.RETRY,
            TaskStatus.WAIT_HUMAN,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.RETRY: {
            TaskStatus.READY,
            TaskStatus.RUNNING,
            TaskStatus.WAIT_HUMAN,
            TaskStatus.PAUSED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.WAIT_HUMAN: {
            TaskStatus.READY,
            TaskStatus.RUNNING,
            TaskStatus.PAUSED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.PAUSED: {TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.CANCELLED},
        TaskStatus.COMPLETED: set(),
        TaskStatus.FAILED: {TaskStatus.RETRY},
        TaskStatus.CANCELLED: set(),
    }

    @classmethod
    def validate(cls, current: str | TaskStatus, target: str | TaskStatus) -> None:
        current_status = TaskStatus(current)
        target_status = TaskStatus(target)
        if target_status not in cls.transitions[current_status]:
            raise InvalidTransition(f"不允许从 {current_status} 流转到 {target_status}")
