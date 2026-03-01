from __future__ import annotations

import importlib
import sqlite3
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient

from domain.run_constants import MOVE_EVENT_STOPPED, MOVE_EVENT_SUCCESS


@pytest.fixture
def app_client(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    db_path = tmp_path / "execution.db"
    monkeypatch.setenv("TALENCE_DB_PATH", str(db_path))
    monkeypatch.setenv("TALENCE_JWT_SECRET", "phase5-test-secret-32-bytes-minimum-key")

    sys.modules.pop("robot.app.auth", None)
    sys.modules.pop("robot.app.main", None)
    app_mod = importlib.import_module("robot.app.main")
    return TestClient(app_mod.app), str(db_path)


def _db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _headers(client: TestClient, email: str, handle: str) -> dict[str, str]:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "handle": handle},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_payload() -> dict[str, Any]:
    return {
        "input_bin": 1,
        "unrecognized_bin": 35,
        "bins": [1, 2, 3, 35],
        "capacities": {"1": 200, "2": 200, "3": 200, "35": 200},
        "operators": [{"op": "color_identity", "order": 0}],
        "purge_sort_enabled": False,
    }


def _prepare_planned_run(client: TestClient, headers: dict[str, str], suffix: str) -> tuple[str, str]:
    run_id = client.post("/runs/create_local", json=_create_payload(), headers=headers).json()["run_id"]
    assert client.post(f"/runs/{run_id}/start_scanning", headers=headers).status_code == 200
    assert client.post(f"/runs/{run_id}/holding_ready", headers=headers).status_code == 200

    for idx in range(2):
        added = client.post(
            f"/runs/{run_id}/debug_add_card",
            headers=headers,
            json={
                "name": f"Card {suffix} {idx}",
                "oracle_id": f"o-{suffix}-{idx}",
                "print_id": f"p-{suffix}-{idx}",
                "identified": True,
                "current_bin": 1,
                "attrs": {"colors": ["W"], "color_identity": ["W"]},
            },
        )
        assert added.status_code == 200

    planned = client.post(f"/runs/{run_id}/plan", headers=headers)
    assert planned.status_code == 200
    return run_id, str(planned.json()["plan_id"])


def test_execute_writes_success_events_and_completes(app_client: tuple[TestClient, str]) -> None:
    client, db_path = app_client
    headers = _headers(client, "exec1@example.com", "exec1")
    run_id, plan_id = _prepare_planned_run(client, headers, "a")

    executed = client.post(f"/runs/{run_id}/execute", headers=headers)
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "COMPLETE"
    assert body["plan_id"] == plan_id
    assert body["executed_steps"] > 0

    con = _db(db_path)
    planned_moves_count = int(
        con.execute("SELECT COUNT(*) AS n FROM planned_moves WHERE plan_id = ?", (plan_id,)).fetchone()["n"]
    )
    success_count = int(
        con.execute(
            "SELECT COUNT(*) AS n FROM move_events WHERE plan_id = ? AND status = ?",
            (plan_id, MOVE_EVENT_SUCCESS),
        ).fetchone()["n"]
    )
    run_status = con.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()["status"]
    con.close()

    assert success_count == planned_moves_count
    assert run_status == "COMPLETE"


def test_execute_resumes_from_last_success(app_client: tuple[TestClient, str]) -> None:
    client, db_path = app_client
    headers = _headers(client, "exec2@example.com", "exec2")
    run_id, plan_id = _prepare_planned_run(client, headers, "b")

    con = _db(db_path)
    first_move = con.execute(
        "SELECT step_no, from_bin, to_bin, instance_id FROM planned_moves WHERE plan_id = ? ORDER BY step_no ASC LIMIT 1",
        (plan_id,),
    ).fetchone()
    assert first_move is not None
    con.execute(
        """
        INSERT INTO move_events (
          id, plan_id, step_no, timestamp, from_bin, to_bin, instance_id, status, error, hardware_txn_id
        )
        VALUES ('seed-success', ?, ?, datetime('now'), ?, ?, ?, ?, NULL, NULL)
        """,
        (
            plan_id,
            int(first_move["step_no"]),
            int(first_move["from_bin"]) if first_move["from_bin"] is not None else None,
            int(first_move["to_bin"]) if first_move["to_bin"] is not None else None,
            first_move["instance_id"],
            MOVE_EVENT_SUCCESS,
        ),
    )
    con.commit()
    con.close()

    executed = client.post(f"/runs/{run_id}/execute", headers=headers)
    assert executed.status_code == 200
    assert executed.json()["status"] == "COMPLETE"

    con = _db(db_path)
    step0_success = int(
        con.execute(
            "SELECT COUNT(*) AS n FROM move_events WHERE plan_id = ? AND step_no = 0 AND status = ?",
            (plan_id, MOVE_EVENT_SUCCESS),
        ).fetchone()["n"]
    )
    planned_moves_count = int(
        con.execute("SELECT COUNT(*) AS n FROM planned_moves WHERE plan_id = ?", (plan_id,)).fetchone()["n"]
    )
    success_count = int(
        con.execute(
            "SELECT COUNT(*) AS n FROM move_events WHERE plan_id = ? AND status = ?",
            (plan_id, MOVE_EVENT_SUCCESS),
        ).fetchone()["n"]
    )
    con.close()

    assert step0_success == 1
    assert success_count == planned_moves_count


def test_stop_endpoint_persists_stopped_and_sets_planned(app_client: tuple[TestClient, str]) -> None:
    client, db_path = app_client
    headers = _headers(client, "exec3@example.com", "exec3")
    run_id, plan_id = _prepare_planned_run(client, headers, "c")

    con = _db(db_path)
    con.execute(
        "UPDATE runs SET status = 'EXECUTING', stop_requested = 1 WHERE id = ?",
        (run_id,),
    )
    con.commit()
    con.close()

    stopped = client.post(f"/runs/{run_id}/stop", headers=headers)
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "PLANNED"

    con = _db(db_path)
    run_row = con.execute("SELECT status, stop_requested FROM runs WHERE id = ?", (run_id,)).fetchone()
    stopped_count = int(
        con.execute(
            "SELECT COUNT(*) AS n FROM move_events WHERE plan_id = ? AND status = ?",
            (plan_id, MOVE_EVENT_STOPPED),
        ).fetchone()["n"]
    )
    con.close()

    assert run_row is not None
    assert run_row["status"] == "PLANNED"
    assert int(run_row["stop_requested"]) == 0
    assert stopped_count >= 1


def test_execute_honors_stop_requested_then_resumes(app_client: tuple[TestClient, str]) -> None:
    client, db_path = app_client
    headers = _headers(client, "exec4@example.com", "exec4")
    run_id, plan_id = _prepare_planned_run(client, headers, "d")

    con = _db(db_path)
    con.execute("UPDATE runs SET stop_requested = 1 WHERE id = ?", (run_id,))
    con.commit()
    con.close()

    first = client.post(f"/runs/{run_id}/execute", headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "PLANNED"
    assert first.json()["executed_steps"] == 0

    second = client.post(f"/runs/{run_id}/execute", headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "COMPLETE"

    con = _db(db_path)
    success_count = int(
        con.execute(
            "SELECT COUNT(*) AS n FROM move_events WHERE plan_id = ? AND status = ?",
            (plan_id, MOVE_EVENT_SUCCESS),
        ).fetchone()["n"]
    )
    planned_moves_count = int(
        con.execute("SELECT COUNT(*) AS n FROM planned_moves WHERE plan_id = ?", (plan_id,)).fetchone()["n"]
    )
    con.close()

    assert success_count == planned_moves_count
