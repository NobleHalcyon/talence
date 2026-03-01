import sqlite3
from contextlib import contextmanager

import pytest

from domain.run_lifecycle import RunStatus, InvalidTransition
from services.run_service import (
    ActiveRunExists,
    assert_no_active_run,
    fail_run,
    reset_failed_run,
    set_status,
)


RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  collection_id TEXT NOT NULL,
  status TEXT NOT NULL,
  input_bin_id INTEGER NOT NULL DEFAULT 1,
  unrecognized_bin_id INTEGER NOT NULL DEFAULT 35,
  purge_sort_enabled INTEGER NOT NULL DEFAULT 0,
  bins_json TEXT NOT NULL,
  capacities_json TEXT NOT NULL,
  operators_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  failed_code TEXT,
  failed_message TEXT,
  CONSTRAINT ck_runs_status_allowed CHECK (
    status IN ('IDLE','SCANNING','HOLDING_READY','PLANNED','EXECUTING','COMPLETE','FAILED')
  )
);
"""


@contextmanager
def _conn(path: str):
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def db(tmp_path):
    db_path = tmp_path / "test.db"
    with _conn(str(db_path)) as conn:
        conn.executescript(RUNS_SCHEMA)
        conn.commit()
    return str(db_path)


def _insert_run(conn: sqlite3.Connection, *, run_id: str, user_id: str, status: str):
    # Minimal required fields for current schema
    conn.execute(
        """
        INSERT INTO runs (
          id, user_id, collection_id, status,
          bins_json, capacities_json, operators_json,
          created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (run_id, user_id, "COLL1", status, "{}", "{}", "[]"),
    )
    conn.commit()


def _get_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    cur = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
    row = cur.fetchone()
    assert row is not None
    return row


def test_active_run_guard_blocks_second_active(db):
    with _conn(db) as conn:
        user_id = "U1"
        _insert_run(conn, run_id="R1", user_id=user_id, status=RunStatus.SCANNING.value)

        with pytest.raises(ActiveRunExists):
            assert_no_active_run(conn, user_id)


def test_fail_sets_fields_and_traps(db):
    with _conn(db) as conn:
        user_id = "U1"
        _insert_run(conn, run_id="R2", user_id=user_id, status=RunStatus.EXECUTING.value)

        fail_run(conn, "R2", "E_TEST", "boom")

        r = _get_run(conn, "R2")
        assert r["status"] == RunStatus.FAILED.value
        assert r["failed_code"] == "E_TEST"
        assert r["failed_message"] == "boom"

        # Illegal escape: FAILED -> IDLE must use reset_failed_run
        with pytest.raises(InvalidTransition):
            set_status(conn, "R2", RunStatus.IDLE)


def test_reset_failed_clears_fields(db):
    with _conn(db) as conn:
        user_id = "U1"
        _insert_run(conn, run_id="R3", user_id=user_id, status=RunStatus.FAILED.value)

        # Pre-load failure fields
        conn.execute(
            "UPDATE runs SET failed_code = ?, failed_message = ? WHERE id = ?",
            ("E", "m", "R3"),
        )
        conn.commit()

        reset_failed_run(conn, "R3")

        r = _get_run(conn, "R3")
        assert r["status"] == RunStatus.IDLE.value
        assert r["failed_code"] is None
        assert r["failed_message"] is None