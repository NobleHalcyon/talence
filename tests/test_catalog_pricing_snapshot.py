from __future__ import annotations

import importlib
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, object, str]:
    db_path = tmp_path / "pricing_snapshot.db"
    monkeypatch.setenv("TALENCE_DB_PATH", str(db_path))
    monkeypatch.setenv("TALENCE_JWT_SECRET", "pricing-snapshot-test-secret-32-bytes")

    sys.modules.pop("robot.app.auth", None)
    sys.modules.pop("robot.app.main", None)
    sys.modules.pop("robot.app.catalog.pricing", None)

    app_mod = importlib.import_module("robot.app.main")
    return TestClient(app_mod.app), app_mod, str(db_path)


def _headers(client: TestClient, email: str, handle: str) -> dict[str, str]:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "handle": handle},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_payload() -> dict[str, object]:
    return {
        "input_bin": 1,
        "unrecognized_bin": 35,
        "bins": [1, 2, 3, 35],
        "capacities": {"1": 200, "2": 200, "3": 200, "35": 200},
        "operators": [{"op": "alphabetical", "order": 0, "deep": True}],
        "purge_sort_enabled": False,
    }


def _db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def test_price_pull_occurs_once_per_print_per_run(
    app_client: tuple[TestClient, object, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app_mod, _ = app_client
    headers = _headers(client, "once@example.com", "once")

    calls: list[str] = []

    def fake_fetch(print_id: str):
        calls.append(print_id)
        return app_mod.catalog_pricing.PricePoint(
            print_id=print_id,
            price_usd_cents=125,
            price_usd_foil_cents=250,
            source="test",
            fetched_at="2026-03-01T00:00:00+00:00",
            raw_json="{}",
        )

    monkeypatch.setattr(app_mod.catalog_pricing, "_fetch_live_price", fake_fetch)

    run_id = client.post("/runs/create_local", json=_create_payload(), headers=headers).json()["run_id"]
    assert client.post(f"/runs/{run_id}/start_scanning", headers=headers).status_code == 200

    for idx in range(2):
        resp = client.post(
            f"/runs/{run_id}/debug_add_card",
            headers=headers,
            json={
                "name": f"Card {idx}",
                "oracle_id": f"o-{idx}",
                "print_id": "print-same",
                "identified": True,
                "current_bin": 1,
                "attrs": {"color_identity": ["W"]},
            },
        )
        assert resp.status_code == 200

    assert calls == ["print-same"]


def test_snapshot_is_immutable_and_execution_uses_snapshot_only(
    app_client: tuple[TestClient, object, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app_mod, db_path = app_client
    headers = _headers(client, "immut@example.com", "immut")

    monkeypatch.setattr(
        app_mod.catalog_pricing,
        "_fetch_live_price",
        lambda print_id: app_mod.catalog_pricing.PricePoint(
            print_id=print_id,
            price_usd_cents=321,
            price_usd_foil_cents=654,
            source="test",
            fetched_at="2026-03-01T00:00:00+00:00",
            raw_json="{}",
        ),
    )

    run_id = client.post("/runs/create_local", json=_create_payload(), headers=headers).json()["run_id"]
    assert client.post(f"/runs/{run_id}/start_scanning", headers=headers).status_code == 200
    assert (
        client.post(
            f"/runs/{run_id}/debug_add_card",
            headers=headers,
            json={
                "name": "Card A",
                "oracle_id": "o-a",
                "print_id": "print-a",
                "identified": True,
                "current_bin": 1,
                "attrs": {"color_identity": ["W"]},
            },
        ).status_code
        == 200
    )
    assert client.post(f"/runs/{run_id}/holding_ready", headers=headers).status_code == 200
    planned = client.post(f"/runs/{run_id}/plan", headers=headers)
    assert planned.status_code == 200

    con = _db(db_path)
    before = con.execute(
        "SELECT price_usd_cents FROM run_price_snapshots WHERE run_id = ? AND print_id = ?",
        (run_id, "print-a"),
    ).fetchone()
    assert before is not None
    assert int(before["price_usd_cents"]) == 321

    con.execute(
        "UPDATE prices_current SET price_usd_cents = 99999 WHERE print_id = ?",
        ("print-a",),
    )
    con.commit()
    con.close()

    executed = client.post(f"/runs/{run_id}/execute", headers=headers)
    assert executed.status_code == 200
    assert executed.json()["status"] == "COMPLETE"

    verify = _db(db_path)
    after = verify.execute(
        "SELECT price_usd_cents FROM run_price_snapshots WHERE run_id = ? AND print_id = ?",
        (run_id, "print-a"),
    ).fetchone()
    verify.close()
    assert after is not None
    assert int(after["price_usd_cents"]) == 321


def test_plan_blocks_when_snapshot_price_missing(
    app_client: tuple[TestClient, object, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app_mod, _ = app_client
    headers = _headers(client, "missing@example.com", "missing")
    monkeypatch.setattr(app_mod.catalog_pricing, "_fetch_live_price", lambda print_id: None)

    run_id = client.post("/runs/create_local", json=_create_payload(), headers=headers).json()["run_id"]
    assert client.post(f"/runs/{run_id}/start_scanning", headers=headers).status_code == 200
    assert (
        client.post(
            f"/runs/{run_id}/debug_add_card",
            headers=headers,
            json={
                "name": "Card Missing",
                "oracle_id": "o-miss",
                "print_id": "print-miss",
                "identified": True,
                "current_bin": 1,
                "attrs": {"color_identity": ["W"]},
            },
        ).status_code
        == 200
    )
    assert client.post(f"/runs/{run_id}/holding_ready", headers=headers).status_code == 200

    planned = client.post(f"/runs/{run_id}/plan", headers=headers)
    assert planned.status_code == 409
    assert "snapshot incomplete" in planned.text
