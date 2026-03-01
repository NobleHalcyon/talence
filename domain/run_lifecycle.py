from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    IDLE = "IDLE"
    SCANNING = "SCANNING"
    HOLDING_READY = "HOLDING_READY"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


ACTIVE = {
    RunStatus.SCANNING,
    RunStatus.HOLDING_READY,
    RunStatus.PLANNED,
    RunStatus.EXECUTING,
}

TERMINAL = {RunStatus.COMPLETE, RunStatus.FAILED}

TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.IDLE: {RunStatus.SCANNING},
    RunStatus.SCANNING: {RunStatus.HOLDING_READY, RunStatus.FAILED},
    RunStatus.HOLDING_READY: {RunStatus.PLANNED, RunStatus.FAILED},
    RunStatus.PLANNED: {RunStatus.EXECUTING, RunStatus.FAILED},
    RunStatus.EXECUTING: {RunStatus.PLANNED, RunStatus.COMPLETE, RunStatus.FAILED},
    RunStatus.COMPLETE: set(),
    RunStatus.FAILED: set(),
}


class InvalidTransition(ValueError):
    pass


def assert_transition(current: RunStatus, nxt: RunStatus) -> None:
    allowed = TRANSITIONS.get(current, set())
    if nxt not in allowed:
        raise InvalidTransition(f"Invalid run transition: {current} -> {nxt}")


def is_active(status: RunStatus) -> bool:
    return status in ACTIVE


def assert_can_reset_failed(current: RunStatus) -> None:
    if current != RunStatus.FAILED:
        raise InvalidTransition(f"Reset only allowed from FAILED, not {current}")
