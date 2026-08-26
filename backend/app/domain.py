from enum import StrEnum


class EmployeeStatus(StrEnum):
    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    WORKING = "WORKING"
    WAIT_HUMAN = "WAIT_HUMAN"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


class TaskStatus(StrEnum):
    CREATED = "CREATED"
    READY = "READY"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    RETRY = "RETRY"
    WAIT_HUMAN = "WAIT_HUMAN"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class Priority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


PRIORITY_WEIGHT = {Priority.P0: 4, Priority.P1: 3, Priority.P2: 2, Priority.P3: 1}
