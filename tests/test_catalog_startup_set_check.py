from __future__ import annotations

import importlib
import sqlite3
import sys
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_app(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "startup_set_check.db"
    monkeypatch.setenv("TALENCE_DB_PATH", str(db_path))
    monkeypatch.setenv("TALENCE_JWT_SECRET", "startup-set-check-secret-32-bytes")
    monkeypatch.setenv("TALENCE_DISABLE_STARTUP_SET_CHECK", "0")
    sys.modules.pop("robot.app.auth", None)
    sys.modules.pop("robot.app.main", None)
    sys.modules.pop("robot.app.catalog.sync", None)
    app_mod = importlib.import_module("robot.app.main")
    return app_mod, str(db_path)


def _db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def test_startup_set_check_network_unavailable_does_not_break_boot(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_mod, _ = _load_app(tmp_path, monkeypatch)

    def fail_fetch() -> list[str]:
        raise RuntimeError("network down")

    monkeypatch.setattr(app_mod.catalog_sync, "fetch_remote_set_codes", fail_fetch)

    with TestClient(app_mod.app) as client:
        resp = client.get("/status")
        assert resp.status_code == 200


def test_startup_set_check_triggers_delta_ingest_for_new_set_only(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_mod, _ = _load_app(tmp_path, monkeypatch)
    con = app_mod.get_con()
    con.execute(
        """
        INSERT INTO catalog_sets (set_code, scryfall_set_id, name, released_at, set_type, card_count, digital, raw_json, updated_at)
        VALUES ('lea', 'set-lea', 'Limited Edition Alpha', '1993-08-05', 'core', 295, 0, '{}', ?)
        """,
        (_now_iso(),),
    )
    con.commit()
    con.close()

    monkeypatch.setattr(app_mod.catalog_sync, "fetch_remote_set_codes", lambda: ["lea", "neo"])
    ingested: list[str] = []

    def fake_ingest_set_delta(con, *, set_code: str) -> int:
        ingested.append(set_code)
        return 1

    monkeypatch.setattr(app_mod.catalog_sync, "ingest_set_delta", fake_ingest_set_delta)

    with TestClient(app_mod.app) as client:
        assert client.get("/status").status_code == 200
        for _ in range(20):
            if ingested:
                break
            time.sleep(0.01)

    assert ingested == ["neo"]


def test_startup_set_check_does_not_mutate_run_lifecycle(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_mod, db_path = _load_app(tmp_path, monkeypatch)
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
        VALUES ('C1', 'U1', 'G1', 'Default', ?)
        """,
        (ts,),
    )
    con.execute(
        """
        INSERT INTO runs (
          id, user_id, collection_id, status, input_bin_id, unrecognized_bin_id, purge_sort_enabled,
          bins_json, capacities_json, operators_json, created_at, updated_at
        )
        VALUES ('R1', 'U1', 'C1', 'SCANNING', 1, 35, 0, '[1,2,3]', '{"1":200}', '[]', ?, ?)
        """,
        (ts, ts),
    )
    con.commit()
    con.close()

    monkeypatch.setattr(app_mod.catalog_sync, "fetch_remote_set_codes", lambda: [])
    monkeypatch.setattr(app_mod.catalog_sync, "ingest_set_delta", lambda con, set_code: 0)

    with TestClient(app_mod.app) as client:
        assert client.get("/status").status_code == 200
        time.sleep(0.05)

    verify = _db(db_path)
    status = verify.execute("SELECT status FROM runs WHERE id = 'R1'").fetchone()["status"]
    verify.close()
    assert status == "SCANNING"
