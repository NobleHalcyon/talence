from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.run_lifecycle import (
    RunStatus,
    InvalidTransition,
    assert_transition,
    assert_can_reset_failed,
    is_active,
)

# Import your ORM model


class ActiveRunExists(ValueError):
    pass


class RunNotFound(ValueError):
    pass


@dataclass(frozen=True)
class ResumeCandidate:
    run_id: int
    user_id: int
    status: RunStatus


def assert_no_active_run(db: Session, user_id: int) -> None:
    q = select(Run.id, Run.status).where(Run.user_id == user_id)
    rows = db.execute(q).all()
    for run_id, status in rows:
        if is_active(RunStatus(status)):
            raise ActiveRunExists(f"User already has active run {run_id} in status {status}")


def set_status(db: Session, run_id: int, nxt: RunStatus) -> None:
    run = db.get(Run, run_id)
    if run is None:
        raise RunNotFound(f"run {run_id} not found")

    cur = RunStatus(run.status)
    assert_transition(cur, nxt)

    run.status = nxt.value
    db.add(run)
    db.commit()


def fail_run(db: Session, run_id: int, code: str | None, message: str | None) -> None:
    run = db.get(Run, run_id)
    if run is None:
        raise RunNotFound(f"run {run_id} not found")

    cur = RunStatus(run.status)
    assert_transition(cur, RunStatus.FAILED)

    run.status = RunStatus.FAILED.value
    run.failed_code = code
    run.failed_message = message
    db.add(run)
    db.commit()


def reset_failed_run(db: Session, run_id: int) -> None:
    run = db.get(Run, run_id)
    if run is None:
        raise RunNotFound(f"run {run_id} not found")

    cur = RunStatus(run.status)
    assert_can_reset_failed(cur)

    run.status = RunStatus.IDLE.value
    run.failed_code = None
    run.failed_message = None
    db.add(run)
    db.commit()


def get_resume_candidates(db: Session) -> list[ResumeCandidate]:
    q = select(Run.id, Run.user_id, Run.status).where(
        Run.status.in_(["SCANNING", "HOLDING_READY", "PLANNED", "EXECUTING"])
    )
    rows = db.execute(q).all()
    return [ResumeCandidate(run_id=r[0], user_id=r[1], status=RunStatus(r[2])) for r in rows]
