from __future__ import annotations

from domain.run_constants import (
    MOVE_EVENT_ERROR,
    MOVE_EVENT_STOPPED,
    MOVE_EVENT_SUCCESS,
)


def test_move_event_status_constants_are_standardized() -> None:
    assert MOVE_EVENT_SUCCESS == "SUCCESS"
    assert MOVE_EVENT_ERROR == "ERROR"
    assert MOVE_EVENT_STOPPED == "STOPPED"
    assert len({MOVE_EVENT_SUCCESS, MOVE_EVENT_ERROR, MOVE_EVENT_STOPPED}) == 3
