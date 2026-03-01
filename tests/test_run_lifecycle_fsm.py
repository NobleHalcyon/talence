from __future__ import annotations

import pytest

from domain.run_lifecycle import (
    InvalidTransition,
    RunStatus,
    assert_can_reset_failed,
    assert_transition,
)


def test_valid_transition_happy_path() -> None:
    assert_transition(RunStatus.IDLE, RunStatus.SCANNING)
    assert_transition(RunStatus.SCANNING, RunStatus.HOLDING_READY)
    assert_transition(RunStatus.HOLDING_READY, RunStatus.PLANNED)
    assert_transition(RunStatus.PLANNED, RunStatus.EXECUTING)
    assert_transition(RunStatus.EXECUTING, RunStatus.COMPLETE)


@pytest.mark.parametrize(
    "current,nxt",
    [
        (RunStatus.IDLE, RunStatus.PLANNED),
        (RunStatus.COMPLETE, RunStatus.IDLE),
        (RunStatus.FAILED, RunStatus.IDLE),
        (RunStatus.IDLE, RunStatus.FAILED),
    ],
)
def test_invalid_transitions_raise(current: RunStatus, nxt: RunStatus) -> None:
    with pytest.raises(InvalidTransition):
        assert_transition(current, nxt)


def test_reset_only_allowed_from_failed() -> None:
    assert_can_reset_failed(RunStatus.FAILED)
    with pytest.raises(InvalidTransition):
        assert_can_reset_failed(RunStatus.EXECUTING)
