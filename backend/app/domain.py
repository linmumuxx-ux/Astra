from enum import StrEnum


class EmployeeStatus(StrEnum):
    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    WORKING = "WORKING"
    WAIT_HUMAN = "WAIT_HUMAN"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class RuntimeSessionStatus(StrEnum):
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    UNKNOWN = "UNKNOWN"


class SessionTerminalReason(StrEnum):
    COMPLETED = "completed"
    ASSISTANT_ERROR = "assistant_error"
    NO_REPLY = "no_reply"
    ABORTED = "aborted"
    TIMEOUT = "timeout"
    SESSION_MISSING = "session_missing"
    TRANSPORT_UNKNOWN = "transport_unknown"


class ExperienceOrigin(StrEnum):
    RUNTIME = "runtime"
    MANUAL = "manual"
    AUTO = "auto"


class ExperienceType(StrEnum):
    ROOT_CAUSE = "root_cause"
    FIX = "fix"
    ENVIRONMENT = "environment"
    TEST_RULE = "test_rule"
    TOOL_USAGE = "tool_usage"
    OTHER = "other"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING_INPUT = "WAITING_INPUT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SUSPENDED = "SUSPENDED"
    TIMEOUT = "TIMEOUT"
    LOST = "LOST"
    CANCELLED = "CANCELLED"


class RunTriggerReason(StrEnum):
    INITIAL = "INITIAL"
    HUMAN_RESUME = "HUMAN_RESUME"
    WORKER_RECOVERY = "WORKER_RECOVERY"
    USER_CONTINUE = "USER_CONTINUE"
    AUTO_RETRY = "AUTO_RETRY"
    SESSION_RECOVERY = "SESSION_RECOVERY"


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
