from __future__ import annotations

import json
import sqlite3
from typing import Any

from robot.app.catalog.audit import now_iso


def _as_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def upsert_set(con: sqlite3.Connection, set_obj: dict[str, Any], *, updated_at: str) -> None:
    set_code = str(set_obj.get("code") or set_obj.get("set") or "").strip().lower()
    if not set_code:
        return
    con.execute(
        """
        INSERT INTO catalog_sets (
          set_code, scryfall_set_id, name, released_at, set_type, card_count, digital, raw_json, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_code) DO UPDATE SET
          scryfall_set_id = excluded.scryfall_set_id,
          name = excluded.name,
          released_at = excluded.released_at,
          set_type = excluded.set_type,
          card_count = excluded.card_count,
          digital = excluded.digital,
          raw_json = excluded.raw_json,
          updated_at = excluded.updated_at
        """,
        (
            set_code,
            set_obj.get("id"),
            set_obj.get("name") or set_code.upper(),
            set_obj.get("released_at"),
            set_obj.get("set_type"),
            _as_int_or_none(set_obj.get("card_count")),
            1 if bool(set_obj.get("digital", False)) else 0,
            json.dumps(set_obj, separators=(",", ":"), sort_keys=True),
            updated_at,
        ),
    )


def upsert_print(con: sqlite3.Connection, card_obj: dict[str, Any], *, updated_at: str) -> None:
    print_id = str(card_obj.get("id") or "").strip()
    if not print_id:
        return

    image_uris = card_obj.get("image_uris") or {}
    if not isinstance(image_uris, dict):
        image_uris = {}

    set_code = str(card_obj.get("set") or "").strip().lower() or None
    con.execute(
        """
        INSERT INTO catalog_prints (
          print_id, oracle_id, set_code, name, collector_number, rarity, lang,
          image_small_url, image_normal_url, image_large_url, scryfall_uri, raw_json, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(print_id) DO UPDATE SET
          oracle_id = excluded.oracle_id,
          set_code = excluded.set_code,
          name = excluded.name,
          collector_number = excluded.collector_number,
          rarity = excluded.rarity,
          lang = excluded.lang,
          image_small_url = excluded.image_small_url,
          image_normal_url = excluded.image_normal_url,
          image_large_url = excluded.image_large_url,
          scryfall_uri = excluded.scryfall_uri,
          raw_json = excluded.raw_json,
          updated_at = excluded.updated_at
        """,
        (
            print_id,
            card_obj.get("oracle_id"),
            set_code,
            card_obj.get("name") or print_id,
            card_obj.get("collector_number"),
            card_obj.get("rarity"),
            card_obj.get("lang"),
            image_uris.get("small"),
            image_uris.get("normal"),
            image_uris.get("large"),
            card_obj.get("scryfall_uri"),
            json.dumps(card_obj, separators=(",", ":"), sort_keys=True),
            updated_at,
        ),
    )


def upsert_sync_state(
    con: sqlite3.Connection,
    *,
    source: str,
    object_type: str,
    cursor: str | None,
    etag: str | None,
    status: str,
    rows_processed: int,
    last_synced_at: str,
    last_error: str | None,
) -> None:
    con.execute(
        """
        INSERT INTO sync_state (
          source, object_type, cursor, etag, status, rows_processed, last_synced_at, last_error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET
          object_type = excluded.object_type,
          cursor = excluded.cursor,
          etag = excluded.etag,
          status = excluded.status,
          rows_processed = excluded.rows_processed,
          last_synced_at = excluded.last_synced_at,
          last_error = excluded.last_error
        """,
        (
            source,
            object_type,
            cursor,
            etag,
            status,
            rows_processed,
            last_synced_at,
            last_error,
        ),
    )


def consolidate_run_into_collection(con: sqlite3.Connection, *, run_id: str) -> tuple[bool, str]:
    row = con.execute(
        "SELECT collection_id FROM runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"run {run_id} not found")
    collection_id = str(row["collection_id"])

    exists = con.execute(
        "SELECT run_id FROM collection_consolidations WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if exists:
        return (False, collection_id)

    ts = now_iso()
    con.execute("BEGIN")
    try:
        con.execute(
            """
            INSERT INTO collection_cards (collection_id, print_id, quantity, updated_at)
            SELECT ?, print_id, COUNT(*) AS qty, ?
            FROM run_cards
            WHERE run_id = ?
            GROUP BY print_id
            ON CONFLICT(collection_id, print_id) DO UPDATE SET
              quantity = collection_cards.quantity + excluded.quantity,
              updated_at = excluded.updated_at
            """,
            (collection_id, ts, run_id),
        )
        con.execute(
            """
            INSERT INTO collection_consolidations (run_id, collection_id, consolidated_at)
            VALUES (?, ?, ?)
            """,
            (run_id, collection_id, ts),
        )
        con.commit()
    except Exception:
        con.rollback()
        raise

    return (True, collection_id)
