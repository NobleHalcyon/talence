from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from domain.run_lifecycle import InvalidTransition, RunStatus
from robot.app.db import connect, init_db
from services.run_service import (
    ActiveRunExists,
    assert_no_active_run,
    fail_run,
    reset_failed_run,
    set_status,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def con(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    db_path = tmp_path / "phase1.db"
    monkeypatch.setenv("TALENCE_DB_PATH", str(db_path))
    con = connect()
    init_db(con)
    _seed_user_and_collection(con, user_id="U1", collection_id="COL1")
    yield con
    con.close()


def _seed_user_and_collection(con: sqlite3.Connection, user_id: str, collection_id: str) -> None:
    ts = _now_iso()
    con.execute(
        """
        INSERT INTO users (id, email, handle, password_hash, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        """,
        (user_id, f"{user_id.lower()}@example.com", f"h{user_id.lower()}", "x", ts, ts),
    )
    con.execute(
        "INSERT INTO games (id, code, name, created_at) VALUES (?, ?, ?, ?)",
        ("G1", "mtg", "Magic: The Gathering", ts),
    )
    con.execute(
        """
        INSERT INTO collections (id, user_id, game_id, name, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (collection_id, user_id, "G1", "Default", ts),
    )
    con.commit()


def _insert_run(
    con: sqlite3.Connection,
    *,
    run_id: str,
    user_id: str,
    status: str,
    collection_id: str = "COL1",
    operators_json: str = "[]",
    bins_json: str = "[]",
    capacities_json: str = "{}",
) -> None:
    ts = _now_iso()
    con.execute(
        """
        INSERT INTO runs (
          id, user_id, collection_id, status,
          input_bin_id, unrecognized_bin_id, purge_sort_enabled,
          bins_json, capacities_json, operators_json,
          created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            user_id,
            collection_id,
            status,
            1,
            35,
            0,
            bins_json,
            capacities_json,
            operators_json,
            ts,
            ts,
        ),
    )
    con.commit()


def test_status_check_rejects_invalid_value(con: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _insert_run(con, run_id="R_BAD", user_id="U1", status="NOT_A_STATUS")


def test_active_run_guard_blocks_second_active(con: sqlite3.Connection) -> None:
    _insert_run(con, run_id="R1", user_id="U1", status=RunStatus.SCANNING.value)
    with pytest.raises(ActiveRunExists):
        assert_no_active_run(con, "U1")


def test_fail_sets_fields_and_reset_clears_fields(con: sqlite3.Connection) -> None:
    _insert_run(con, run_id="R2", user_id="U1", status=RunStatus.SCANNING.value)

    fail_run(con, "R2", "U1", "E_TEST", "boom")
    row = con.execute("SELECT status, failed_code, failed_message FROM runs WHERE id = ?", ("R2",)).fetchone()
    assert row is not None
    assert row["status"] == RunStatus.FAILED.value
    assert row["failed_code"] == "E_TEST"
    assert row["failed_message"] == "boom"

    with pytest.raises(InvalidTransition):
        set_status(con, "R2", "U1", RunStatus.IDLE)

    reset_failed_run(con, "R2", "U1")
    row = con.execute("SELECT status, failed_code, failed_message FROM runs WHERE id = ?", ("R2",)).fetchone()
    assert row is not None
    assert row["status"] == RunStatus.IDLE.value
    assert row["failed_code"] is None
    assert row["failed_message"] is None


def test_move_events_status_is_free_form(con: sqlite3.Connection) -> None:
    _insert_run(con, run_id="R3", user_id="U1", status=RunStatus.PLANNED.value)
    con.execute(
        """
        INSERT INTO movement_plans (id, run_id, planner_version, dest_sequences_json, notes_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("P1", "R3", "v1", "{}", "{}", _now_iso()),
    )
    con.execute(
        """
        INSERT INTO move_events (
          id, plan_id, step_no, timestamp, from_bin, to_bin, instance_id, status, error, hardware_txn_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("E1", "P1", 0, _now_iso(), 1, 2, None, "CUSTOM_STATUS", None, None),
    )
    con.commit()

    row = con.execute("SELECT status FROM move_events WHERE id = 'E1'").fetchone()
    assert row is not None
    assert row["status"] == "CUSTOM_STATUS"


def test_init_db_migrates_legacy_runs_schema_and_statuses(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "legacy.db"

    legacy = sqlite3.connect(str(db_path))
    legacy.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE users (
          id TEXT PRIMARY KEY,
          email TEXT NOT NULL UNIQUE,
          handle TEXT UNIQUE,
          password_hash TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          last_login_at TEXT
        );

        CREATE TABLE games (
          id TEXT PRIMARY KEY,
          code TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          created_at TEXT NOT NULL
        );

        CREATE TABLE collections (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          game_id TEXT NOT NULL,
          name TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
          FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE RESTRICT
        );

        CREATE TABLE runs (
          id                  TEXT PRIMARY KEY,
          user_id             TEXT NOT NULL,
          collection_id       TEXT NOT NULL,
          status              TEXT NOT NULL,
          input_bin_id        INTEGER NOT NULL DEFAULT 1,
          unrecognized_bin_id INTEGER NOT NULL DEFAULT 35,
          purge_sort_enabled  INTEGER NOT NULL DEFAULT 0 CHECK (purge_sort_enabled IN (0,1)),
          bins_json           TEXT NOT NULL,
          capacities_json     TEXT NOT NULL,
          operators_json      TEXT NOT NULL,
          created_at          TEXT NOT NULL,
          updated_at          TEXT NOT NULL,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
          FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
        );
        """
    )
    ts = _now_iso()
    legacy.execute(
        """
        INSERT INTO users (id, email, handle, password_hash, is_active, created_at, updated_at)
        VALUES ('U1', 'u1@example.com', 'u1', 'x', 1, ?, ?)
        """,
        (ts, ts),
    )
    legacy.execute(
        "INSERT INTO games (id, code, name, created_at) VALUES ('G1', 'mtg', 'Magic: The Gathering', ?)",
        (ts,),
    )
    legacy.execute(
        """
        INSERT INTO collections (id, user_id, game_id, name, created_at)
        VALUES ('COL1', 'U1', 'G1', 'Default', ?)
        """,
        (ts,),
    )
    legacy.executemany(
        """
        INSERT INTO runs (
          id, user_id, collection_id, status,
          input_bin_id, unrecognized_bin_id, purge_sort_enabled,
          bins_json, capacities_json, operators_json,
          created_at, updated_at
        )
        VALUES (?, 'U1', 'COL1', ?, 1, 35, 0, '[]', '{}', '[]', ?, ?)
        """,
        [
            ("R_CREATED", "created", ts, ts),
            ("R_PLANNED", "planned", ts, ts),
            ("R_UNKNOWN", "weird_status", ts, ts),
            ("R_SCANNING", "SCANNING", ts, ts),
        ],
    )
    legacy.commit()
    legacy.close()

    monkeypatch.setenv("TALENCE_DB_PATH", str(db_path))
    migrated = connect()
    init_db(migrated)

    rows = migrated.execute("SELECT id, status FROM runs ORDER BY id").fetchall()
    normalized = {row["id"]: row["status"] for row in rows}
    assert normalized["R_CREATED"] == RunStatus.IDLE.value
    assert normalized["R_PLANNED"] == RunStatus.PLANNED.value
    assert normalized["R_UNKNOWN"] == RunStatus.IDLE.value
    assert normalized["R_SCANNING"] == RunStatus.SCANNING.value

    columns = {
        row["name"]
        for row in migrated.execute("PRAGMA table_info(runs)").fetchall()
    }
    assert {"failed_code", "failed_message", "stop_requested"}.issubset(columns)

    with pytest.raises(sqlite3.IntegrityError):
        migrated.execute(
            """
            INSERT INTO runs (
              id, user_id, collection_id, status, bins_json, capacities_json, operators_json, created_at, updated_at
            )
            VALUES ('R_BAD', 'U1', 'COL1', 'INVALID', '[]', '{}', '[]', ?, ?)
            """,
            (_now_iso(), _now_iso()),
        )
        migrated.commit()

    migrated.close()
