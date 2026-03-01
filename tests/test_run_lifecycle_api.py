from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_path = tmp_path / "api.db"
    monkeypatch.setenv("TALENCE_DB_PATH", str(db_path))
    monkeypatch.setenv("TALENCE_JWT_SECRET", "phase2-test-secret-32-bytes-minimum-key")

    # Force a clean import with test env values.
    if "robot.app.auth" in sys.modules:
        sys.modules.pop("robot.app.auth", None)
    if "robot.app.main" in sys.modules:
        sys.modules.pop("robot.app.main", None)

    app_mod = importlib.import_module("robot.app.main")
    return TestClient(app_mod.app)


def _auth_headers(client: TestClient, email: str, handle: str) -> dict[str, str]:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "handle": handle},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_local_payload() -> dict[str, Any]:
    return {
        "input_bin": 1,
        "unrecognized_bin": 35,
        "bins": [1, 2, 3, 35],
        "capacities": {"1": 200, "2": 200, "3": 200, "35": 200},
        "operators": [{"op": "color_identity", "order": 0}],
        "purge_sort_enabled": False,
    }


def test_create_local_blocks_when_user_has_active_run(client: TestClient) -> None:
    headers = _auth_headers(client, "active@example.com", "active")
    r1 = client.post("/runs/create_local", json=_create_local_payload(), headers=headers)
    assert r1.status_code == 200
    run_id = r1.json()["run_id"]

    start = client.post(f"/runs/{run_id}/start_scanning", headers=headers)
    assert start.status_code == 200

    r2 = client.post("/runs/create_local", json=_create_local_payload(), headers=headers)
    assert r2.status_code == 409


def test_transition_endpoints_enforce_fsm(client: TestClient) -> None:
    headers = _auth_headers(client, "fsm@example.com", "fsm")
    run_id = client.post("/runs/create_local", json=_create_local_payload(), headers=headers).json()["run_id"]

    bad = client.post(f"/runs/{run_id}/holding_ready", headers=headers)
    assert bad.status_code == 409

    s1 = client.post(f"/runs/{run_id}/start_scanning", headers=headers)
    assert s1.status_code == 200
    assert s1.json()["status"] == "SCANNING"

    s2 = client.post(f"/runs/{run_id}/holding_ready", headers=headers)
    assert s2.status_code == 200
    assert s2.json()["status"] == "HOLDING_READY"


def test_plan_requires_holding_ready(client: TestClient) -> None:
    headers = _auth_headers(client, "plan@example.com", "plan")
    run_id = client.post("/runs/create_local", json=_create_local_payload(), headers=headers).json()["run_id"]

    early = client.post(f"/runs/{run_id}/plan", headers=headers)
    assert early.status_code == 409

    client.post(f"/runs/{run_id}/start_scanning", headers=headers)
    client.post(f"/runs/{run_id}/holding_ready", headers=headers)
    planned = client.post(f"/runs/{run_id}/plan", headers=headers)
    assert planned.status_code == 200
    assert "plan_id" in planned.json()


def test_fail_and_reset_failed_endpoints(client: TestClient) -> None:
    headers = _auth_headers(client, "fail@example.com", "fail")
    run_id = client.post("/runs/create_local", json=_create_local_payload(), headers=headers).json()["run_id"]

    bad_fail = client.post(
        f"/runs/{run_id}/fail",
        json={"failed_code": "E_BAD", "failed_message": "bad"},
        headers=headers,
    )
    assert bad_fail.status_code == 409

    client.post(f"/runs/{run_id}/start_scanning", headers=headers)
    failed = client.post(
        f"/runs/{run_id}/fail",
        json={"failed_code": "E_TEST", "failed_message": "boom"},
        headers=headers,
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "FAILED"

    reset = client.post(f"/runs/{run_id}/reset_failed", headers=headers)
    assert reset.status_code == 200
    assert reset.json()["status"] == "IDLE"
