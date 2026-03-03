from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from robot.app.catalog.images import cache_print_face_image
from robot.app.db import connect, init_db


@pytest.fixture
def con(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> tuple[sqlite3.Connection, str]:
    db_path = tmp_path / "catalog_images.db"
    monkeypatch.setenv("TALENCE_DB_PATH", str(db_path))
    con = connect()
    init_db(con)
    ts = "2026-03-01T00:00:00+00:00"
    con.execute(
        """
        INSERT INTO catalog_prints (
          print_id, oracle_id, set_code, name, collector_number, rarity, lang,
          image_small_url, image_normal_url, image_large_url, scryfall_uri, raw_json, updated_at
        )
        VALUES ('print-1', 'oracle-1', NULL, 'Card One', '1', 'rare', 'en', NULL, NULL, NULL, NULL, '{}', ?)
        """,
        (ts,),
    )
    con.commit()
    yield con, str(tmp_path)
    con.close()


def test_image_cache_hash_shard_path_and_idempotency(con: tuple[sqlite3.Connection, str]) -> None:
    db, tmp_root = con
    payload = b"mock-image-bytes-1"
    expected_sha = hashlib.sha256(payload).hexdigest()
    expected_rel = f"data/images/{expected_sha[:2]}/{expected_sha[2:4]}/{expected_sha}.jpg"

    first = cache_print_face_image(
        db,
        print_id="print-1",
        face_key="front",
        source_url="https://img.example/card-one.jpg",
        data_root=Path(tmp_root) / "data",
        image_bytes=payload,
    )
    second = cache_print_face_image(
        db,
        print_id="print-1",
        face_key="front",
        source_url="https://img.example/card-one.jpg",
        data_root=Path(tmp_root) / "data",
        image_bytes=payload,
    )

    row = db.execute(
        "SELECT sha256, local_path, phash FROM print_face_images WHERE print_id = ? AND face_key = ?",
        ("print-1", "front"),
    ).fetchone()
    count = int(
        db.execute(
            "SELECT COUNT(*) AS n FROM print_face_images WHERE print_id = ? AND face_key = ?",
            ("print-1", "front"),
        ).fetchone()["n"]
    )

    assert first["sha256"] == expected_sha
    assert first["local_path"] == expected_rel
    assert Path(first["absolute_path"]).exists()
    assert second["sha256"] == expected_sha
    assert second["local_path"] == expected_rel
    assert row is not None
    assert row["sha256"] == expected_sha
    assert row["local_path"] == expected_rel
    assert row["phash"] is None
    assert count == 1
