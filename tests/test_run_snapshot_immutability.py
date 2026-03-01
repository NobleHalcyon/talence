from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from domain.run_constants import FROZEN_RUN_SNAPSHOT_FIELDS
from domain.run_lifecycle import RunStatus
from robot.app.db import connect, init_db
from services.run_service import fail_run, reset_failed_run, set_status


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def con(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    db_path = tmp_path / "immutability.db"
    monkeypatch.setenv("TALENCE_DB_PATH", str(db_path))
    con = connect()
    init_db(con)
    _seed_user_and_collection(con)
    yield con
    con.close()


def _seed_user_and_collection(con: sqlite3.Connection) -> None:
    ts = _now_iso()
    con.execute(
        """
        INSERT INTO users (id, email, handle, password_hash, is_active, created_at, updated_at)
        VALUES ('U1', 'u1@example.com', 'u1', 'x', 1, ?, ?)
        """,
        (ts, ts),
    )
    con.execute(
        "INSERT INTO games (id, code, name, created_at) VALUES ('G1', 'mtg', 'Magic: The Gathering', ?)",
        (ts,),
    )
    con.execute(
        """
        INSERT INTO collections (id, user_id, game_id, name, created_at)
        VALUES ('COL1', 'U1', 'G1', 'Default', ?)
        """,
        (ts,),
    )
    con.commit()


def _snapshot_fields(con: sqlite3.Connection, run_id: str) -> tuple[str, ...]:
    row = con.execute(
        """
        SELECT operators_json, bins_json, capacities_json
        FROM runs
        WHERE id = ?
        """,
        (run_id,),
    ).fetchone()
    assert row is not None
    return tuple(str(row[f]) for f in FROZEN_RUN_SNAPSHOT_FIELDS)


def test_lifecycle_mutations_do_not_change_frozen_snapshot_fields(con: sqlite3.Connection) -> None:
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
            "R1",
            "U1",
            "COL1",
            RunStatus.IDLE.value,
            1,
            35,
            0,
            "[1,2,3]",
            '{"1":200,"2":200,"3":200}',
            '[{"op":"color_identity","order":0}]',
            ts,
            ts,
        ),
    )
    con.commit()

    before = _snapshot_fields(con, "R1")

    set_status(con, "R1", "U1", RunStatus.SCANNING)
    assert _snapshot_fields(con, "R1") == before

    fail_run(con, "R1", "U1", "E_X", "failed")
    assert _snapshot_fields(con, "R1") == before

    reset_failed_run(con, "R1", "U1")
    assert _snapshot_fields(con, "R1") == before
