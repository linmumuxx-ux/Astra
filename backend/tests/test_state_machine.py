import pytest

from app.domain import TaskStatus
from app.state_machine import InvalidTransition, TaskStateMachine


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.READY, TaskStatus.RUNNING),
        (TaskStatus.READY, TaskStatus.SUSPENDED),
        (TaskStatus.RUNNING, TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, TaskStatus.WAIT_HUMAN),
        (TaskStatus.WAIT_HUMAN, TaskStatus.RUNNING),
        (TaskStatus.WAIT_HUMAN, TaskStatus.READY),
        (TaskStatus.SUSPENDED, TaskStatus.RUNNING),
        (TaskStatus.SUSPENDED, TaskStatus.READY),
        (TaskStatus.RUNNING, TaskStatus.PENDING_CONFIRMATION),
        (TaskStatus.RUNNING, TaskStatus.EXECUTION_ERROR),
        (TaskStatus.PENDING_CONFIRMATION, TaskStatus.COMPLETED),
        (TaskStatus.EXECUTION_ERROR, TaskStatus.RUNNING),
    ],
)
def test_valid_v04_transitions(current, target):
    TaskStateMachine.validate(current, target)


@pytest.mark.parametrize(
    "terminal",
    [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED],
)
def test_terminal_statuses_cannot_restart(terminal):
    with pytest.raises(InvalidTransition):
        TaskStateMachine.validate(terminal, TaskStatus.RUNNING)


def test_ready_cannot_complete_without_working():
    with pytest.raises(InvalidTransition):
        TaskStateMachine.validate(TaskStatus.READY, TaskStatus.COMPLETED)
