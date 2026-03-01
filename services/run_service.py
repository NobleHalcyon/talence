from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3

from domain.run_lifecycle import (
    InvalidTransition,
    RunStatus,
    assert_can_reset_failed,
    assert_transition,
    is_active,
)


class ActiveRunExists(ValueError):
    pass


class RunNotFound(ValueError):
    pass


@dataclass(frozen=True)
class ResumeCandidate:
    run_id: str
    user_id: str
    status: RunStatus


_LEGACY_STATUS_MAP = {
    "CREATED": RunStatus.IDLE,
    "PLANNED": RunStatus.PLANNED,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_status(status: str | None) -> RunStatus:
    if status is None:
        return RunStatus.IDLE
    s = status.strip().upper()
    if s in _LEGACY_STATUS_MAP:
        return _LEGACY_STATUS_MAP[s]
    try:
        return RunStatus(s)
    except ValueError:
        return RunStatus.IDLE


def _get_owned_run(con: sqlite3.Connection, run_id: str, user_id: str) -> sqlite3.Row:
    row = con.execute(
        """
        SELECT id, user_id, status
        FROM runs
        WHERE id = ? AND user_id = ?
        """,
        (run_id, user_id),
    ).fetchone()
    if not row:
        raise RunNotFound(f"run {run_id} not found")
    return row


def assert_no_active_run(con: sqlite3.Connection, user_id: str) -> None:
    rows = con.execute(
        "SELECT id, status FROM runs WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    for row in rows:
        status = _normalize_status(row["status"])
        if is_active(status):
            raise ActiveRunExists(
                f"User already has active run {row['id']} in status {status.value}"
            )


def set_status(
    con: sqlite3.Connection,
    run_id: str,
    user_id: str,
    nxt: RunStatus,
) -> None:
    run = _get_owned_run(con, run_id, user_id)
    current = _normalize_status(run["status"])
    assert_transition(current, nxt)

    con.execute(
        """
        UPDATE runs
        SET status = ?, updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (nxt.value, _now_iso(), run_id, user_id),
    )
    con.commit()


def fail_run(
    con: sqlite3.Connection,
    run_id: str,
    user_id: str,
    code: str | None,
    message: str | None,
) -> None:
    run = _get_owned_run(con, run_id, user_id)
    current = _normalize_status(run["status"])
    assert_transition(current, RunStatus.FAILED)

    con.execute(
        """
        UPDATE runs
        SET status = ?, failed_code = ?, failed_message = ?, updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (RunStatus.FAILED.value, code, message, _now_iso(), run_id, user_id),
    )
    con.commit()


def reset_failed_run(con: sqlite3.Connection, run_id: str, user_id: str) -> None:
    run = _get_owned_run(con, run_id, user_id)
    current = _normalize_status(run["status"])
    assert_can_reset_failed(current)

    con.execute(
        """
        UPDATE runs
        SET status = ?, failed_code = NULL, failed_message = NULL, updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (RunStatus.IDLE.value, _now_iso(), run_id, user_id),
    )
    con.commit()


def get_resume_candidates(con: sqlite3.Connection) -> list[ResumeCandidate]:
    active_statuses = tuple(s.value for s in RunStatus if is_active(s))
    placeholders = ",".join("?" for _ in active_statuses)
    rows = con.execute(
        f"""
        SELECT id, user_id, status
        FROM runs
        WHERE status IN ({placeholders})
        ORDER BY created_at ASC, id ASC
        """,
        active_statuses,
    ).fetchall()
    return [
        ResumeCandidate(
            run_id=row["id"],
            user_id=row["user_id"],
            status=_normalize_status(row["status"]),
        )
        for row in rows
    ]
