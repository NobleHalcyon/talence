import pytest
from domain.run_lifecycle import (
    RunStatus,
    assert_transition,
    assert_can_reset_failed,
    InvalidTransition,
)


def test_valid_idle_to_scanning():
    assert_transition(RunStatus.IDLE, RunStatus.SCANNING)


@pytest.mark.parametrize(
    "cur,nxt",
    [
        (RunStatus.IDLE, RunStatus.PLANNED),
        (RunStatus.COMPLETE, RunStatus.IDLE),
        (RunStatus.FAILED, RunStatus.IDLE),
    ],
)
def test_invalid_transitions(cur, nxt):
    with pytest.raises(InvalidTransition):
        assert_transition(cur, nxt)


def test_reset_only_from_failed():
    assert_can_reset_failed(RunStatus.FAILED)
    with pytest.raises(InvalidTransition):
        assert_can_reset_failed(RunStatus.EXECUTING)