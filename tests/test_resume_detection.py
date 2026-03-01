from __future__ import annotations

import importlib
import logging
import sqlite3
import sys
from datetime import datetime, timezone

from fastapi.testclient import TestClient


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_startup_logs_resume_required_without_mutating_statuses(
    tmp_path, monkeypatch, caplog
) -> None:
    db_path = tmp_path / "resume.db"
    monkeypatch.setenv("TALENCE_DB_PATH", str(db_path))
    monkeypatch.setenv("TALENCE_JWT_SECRET", "phase3-test-secret-32-bytes-minimum-key")

    sys.modules.pop("robot.app.auth", None)
    sys.modules.pop("robot.app.main", None)
    app_mod = importlib.import_module("robot.app.main")

    con = app_mod.get_con()
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

    def insert_run(run_id: str, status: str) -> None:
        con.execute(
            """
            INSERT INTO runs (
              id, user_id, collection_id, status,
              input_bin_id, unrecognized_bin_id, purge_sort_enabled,
              bins_json, capacities_json, operators_json,
              created_at, updated_at
            )
            VALUES (?, 'U1', 'COL1', ?, 1, 35, 0, '[]', '{}', '[]', ?, ?)
            """,
            (run_id, status, ts, ts),
        )

    insert_run("R_SCAN", "SCANNING")
    insert_run("R_HOLD", "HOLDING_READY")
    insert_run("R_PLAN", "PLANNED")
    insert_run("R_EXEC", "EXECUTING")
    insert_run("R_DONE", "COMPLETE")
    con.commit()
    con.close()

    caplog.set_level(logging.WARNING)
    with TestClient(app_mod.app) as client:
        assert client.get("/status").status_code == 200

    messages = [record.getMessage() for record in caplog.records if "Run resume required" in record.getMessage()]
    assert any("run_id=R_SCAN" in m and "status=SCANNING" in m for m in messages)
    assert any("run_id=R_HOLD" in m and "status=HOLDING_READY" in m for m in messages)
    assert any("run_id=R_PLAN" in m and "status=PLANNED" in m for m in messages)
    assert any("run_id=R_EXEC" in m and "status=EXECUTING" in m for m in messages)
    assert all("run_id=R_DONE" not in m for m in messages)

    verify = sqlite3.connect(str(db_path))
    rows = verify.execute("SELECT id, status FROM runs ORDER BY id").fetchall()
    verify.close()
    status_by_id = {row[0]: row[1] for row in rows}
    assert status_by_id["R_SCAN"] == "SCANNING"
    assert status_by_id["R_HOLD"] == "HOLDING_READY"
    assert status_by_id["R_PLAN"] == "PLANNED"
    assert status_by_id["R_EXEC"] == "EXECUTING"
    assert status_by_id["R_DONE"] == "COMPLETE"
