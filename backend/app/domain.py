from enum import StrEnum


class EmployeeStatus(StrEnum):
    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    WORKING = "WORKING"
    WAIT_HUMAN = "WAIT_HUMAN"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


class TaskStatus(StrEnum):
    READY = "READY"
    RUNNING = "RUNNING"
    WAIT_HUMAN = "WAIT_HUMAN"
    SUSPENDED = "SUSPENDED"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    CANCELLED = "CANCELLED"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class ExecutionMode(StrEnum):
    LOCAL = "LOCAL"
    LINUX_REMOTE = "LINUX_REMOTE"


class EnvironmentStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    CHECKING = "CHECKING"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class Priority(StrEnum):
    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class TaskType(StrEnum):
    ISSUE = "ISSUE"
    REQUIREMENT = "REQUIREMENT"


class AcceptanceStatus(StrEnum):
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    UNCONFIRMED = "UNCONFIRMED"


class CompletionPolicy(StrEnum):
    AUTO = "AUTO"
    MANUAL_CONFIRM = "MANUAL_CONFIRM"


PRIORITY_WEIGHT = {
    Priority.VERY_HIGH: 4,
    Priority.HIGH: 3,
    Priority.MEDIUM: 2,
    Priority.LOW: 1,
}
