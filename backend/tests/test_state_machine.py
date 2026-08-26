import pytest

from app.domain import TaskStatus
from app.state_machine import InvalidTransition, TaskStateMachine


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.CREATED, TaskStatus.READY),
        (TaskStatus.READY, TaskStatus.CLAIMED),
        (TaskStatus.RUNNING, TaskStatus.VERIFYING),
        (TaskStatus.VERIFYING, TaskStatus.COMPLETED),
        (TaskStatus.RETRY, TaskStatus.RUNNING),
        (TaskStatus.WAIT_HUMAN, TaskStatus.RUNNING),
        (TaskStatus.WAIT_HUMAN, TaskStatus.READY),
    ],
)
def test_valid_transitions(current, target):
    TaskStateMachine.validate(current, target)


def test_completed_is_terminal():
    with pytest.raises(InvalidTransition):
        TaskStateMachine.validate(TaskStatus.COMPLETED, TaskStatus.RUNNING)


def test_cannot_skip_verification():
    with pytest.raises(InvalidTransition):
        TaskStateMachine.validate(TaskStatus.RUNNING, TaskStatus.COMPLETED)
