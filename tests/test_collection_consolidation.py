from __future__ import annotations

import importlib
import sqlite3
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    db_path = tmp_path / "collection_consolidation.db"
    monkeypatch.setenv("TALENCE_DB_PATH", str(db_path))
    monkeypatch.setenv("TALENCE_JWT_SECRET", "collection-consolidation-secret-32-bytes")
    sys.modules.pop("robot.app.auth", None)
    sys.modules.pop("robot.app.main", None)
    app_mod = importlib.import_module("robot.app.main")
    return TestClient(app_mod.app), str(db_path)


def _headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/auth/register",
        json={"email": "consol@example.com", "password": "password123", "handle": "consol"},
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
        "operators": [{"op": "alphabetical", "order": 0, "deep": True}],
        "purge_sort_enabled": False,
    }


def _db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def test_collection_consolidation_is_idempotent_with_correct_quantities(
    app_client: tuple[TestClient, str]
) -> None:
    client, db_path = app_client
    headers = _headers(client)
    run_id = client.post("/runs/create_local", json=_create_payload(), headers=headers).json()["run_id"]

    for card in [
        {"name": "A1", "oracle_id": "o-a", "print_id": "print-a"},
        {"name": "A2", "oracle_id": "o-a", "print_id": "print-a"},
        {"name": "B1", "oracle_id": "o-b", "print_id": "print-b"},
    ]:
        resp = client.post(
            f"/runs/{run_id}/debug_add_card",
            headers=headers,
            json={
                "name": card["name"],
                "oracle_id": card["oracle_id"],
                "print_id": card["print_id"],
                "identified": True,
                "current_bin": 1,
                "attrs": {},
            },
        )
        assert resp.status_code == 200

    first = client.post(f"/runs/{run_id}/consolidate_collection", headers=headers)
    assert first.status_code == 200
    assert first.json()["consolidated"] is True
    collection_id = first.json()["collection_id"]

    second = client.post(f"/runs/{run_id}/consolidate_collection", headers=headers)
    assert second.status_code == 200
    assert second.json()["consolidated"] is False

    con = _db(db_path)
    rows = con.execute(
        """
        SELECT print_id, quantity
        FROM collection_cards
        WHERE collection_id = ?
        ORDER BY print_id
        """,
        (collection_id,),
    ).fetchall()
    ledger_count = int(
        con.execute(
            "SELECT COUNT(*) AS n FROM collection_consolidations WHERE run_id = ?",
            (run_id,),
        ).fetchone()["n"]
    )
    con.close()

    assert [(str(r["print_id"]), int(r["quantity"])) for r in rows] == [
        ("print-a", 2),
        ("print-b", 1),
    ]
    assert ledger_count == 1

