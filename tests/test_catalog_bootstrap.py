from __future__ import annotations

import importlib
import json
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, object, str]:
    db_path = tmp_path / "catalog_bootstrap.db"
    monkeypatch.setenv("TALENCE_DB_PATH", str(db_path))
    monkeypatch.setenv("TALENCE_JWT_SECRET", "catalog-bootstrap-test-secret-32-bytes")

    sys.modules.pop("robot.app.auth", None)
    sys.modules.pop("robot.app.main", None)
    sys.modules.pop("robot.app.catalog.sync", None)

    app_mod = importlib.import_module("robot.app.main")
    return TestClient(app_mod.app), app_mod, str(db_path)


def _auth_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/auth/register",
        json={"email": "catalog@example.com", "password": "password123", "handle": "catalog"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_catalog_bootstrap_ingests_idempotently_and_audits(
    app_client: tuple[TestClient, object, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app_mod, db_path = app_client
    headers = _auth_headers(client)

    bulk_uri = "https://example.local/default_cards.json"
    bulk_payload = {
        "data": [
            {
                "type": "default_cards",
                "download_uri": bulk_uri,
                "updated_at": "2026-03-01T00:00:00.000+00:00",
            }
        ]
    }
    cards_payload = [
        {
            "id": "print-1",
            "oracle_id": "oracle-1",
            "name": "Card One",
            "set": "lea",
            "set_id": "set-1",
            "set_name": "Limited Edition Alpha",
            "released_at": "1993-08-05",
            "collector_number": "1",
            "rarity": "rare",
            "lang": "en",
            "scryfall_uri": "https://scryfall.com/card/lea/1",
            "image_uris": {"normal": "https://img.example/card-one.jpg"},
        },
        {
            "id": "print-2",
            "oracle_id": "oracle-2",
            "name": "Card Two",
            "set": "lea",
            "set_id": "set-1",
            "set_name": "Limited Edition Alpha",
            "released_at": "1993-08-05",
            "collector_number": "2",
            "rarity": "uncommon",
            "lang": "en",
            "scryfall_uri": "https://scryfall.com/card/lea/2",
            "image_uris": {"normal": "https://img.example/card-two.jpg"},
        },
    ]

    def fake_get_json(url: str, *, timeout: float = 45.0):
        if url == app_mod.catalog_sync.SCRYFALL_BULK_ENDPOINT:
            return bulk_payload
        if url == bulk_uri:
            return cards_payload
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(app_mod.catalog_sync, "_http_get_json", fake_get_json)

    first = client.post("/catalog/bootstrap", headers=headers, json={"bulk_type": "default_cards"})
    assert first.status_code == 200
    assert first.json()["rows_ingested"] == 2

    second = client.post("/catalog/bootstrap", headers=headers, json={"bulk_type": "default_cards"})
    assert second.status_code == 200
    assert second.json()["rows_ingested"] == 2

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    prints_count = int(con.execute("SELECT COUNT(*) AS n FROM catalog_prints").fetchone()["n"])
    sets_count = int(con.execute("SELECT COUNT(*) AS n FROM catalog_sets").fetchone()["n"])
    sync_row = con.execute(
        "SELECT source, status, rows_processed FROM sync_state WHERE source = ?",
        ("scryfall.bulk.default_cards",),
    ).fetchone()
    raw_row = con.execute(
        "SELECT raw_json FROM catalog_prints WHERE print_id = ?",
        ("print-1",),
    ).fetchone()
    audit_count = int(
        con.execute(
            """
            SELECT COUNT(*) AS n
            FROM catalog_audit_log
            WHERE event_type = 'catalog_ingest' AND source = 'scryfall.bulk.default_cards' AND status = 'success'
            """
        ).fetchone()["n"]
    )
    con.close()

    assert prints_count == 2
    assert sets_count == 1
    assert sync_row is not None
    assert sync_row["status"] == "success"
    assert int(sync_row["rows_processed"]) == 2
    assert raw_row is not None
    assert json.loads(raw_row["raw_json"])["id"] == "print-1"
    assert audit_count >= 2
