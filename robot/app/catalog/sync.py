from __future__ import annotations

import asyncio
import os
import sqlite3
from typing import Any

import httpx

from robot.app.catalog.audit import now_iso, write_audit_log
from robot.app.catalog.upsert import upsert_print, upsert_set, upsert_sync_state

SCRYFALL_BULK_ENDPOINT = "https://api.scryfall.com/bulk-data"
SCRYFALL_SETS_ENDPOINT = "https://api.scryfall.com/sets"
SCRYFALL_SET_PRINTS_ENDPOINT = (
    "https://api.scryfall.com/cards/search?order=set&q=e%3A{set_code}&unique=prints"
)


def _http_get_json(url: str, *, timeout: float = 45.0) -> Any:
    resp = httpx.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _select_bulk_meta(payload: dict[str, Any], bulk_type: str) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Unexpected bulk metadata shape")
    for row in data:
        if isinstance(row, dict) and str(row.get("type")) == bulk_type:
            return row
    raise ValueError(f"Bulk type not found: {bulk_type}")


def _iter_cards_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
    raise ValueError("Unexpected card payload shape")


def _ingest_cards_transaction(
    con: sqlite3.Connection,
    *,
    cards: list[dict[str, Any]],
    source: str,
    cursor: str | None,
    now_ts: str,
    object_type: str,
) -> int:
    rows = 0
    con.execute("BEGIN")
    try:
        for card in cards:
            set_payload = {
                "id": card.get("set_id"),
                "code": card.get("set"),
                "name": card.get("set_name"),
                "released_at": card.get("released_at"),
                "set_type": card.get("set_type"),
                "digital": card.get("digital", False),
            }
            upsert_set(con, set_payload, updated_at=now_ts)
            upsert_print(con, card, updated_at=now_ts)
            rows += 1

        upsert_sync_state(
            con,
            source=source,
            object_type=object_type,
            cursor=cursor,
            etag=None,
            status="success",
            rows_processed=rows,
            last_synced_at=now_ts,
            last_error=None,
        )
        write_audit_log(
            con,
            event_type="catalog_ingest",
            source=source,
            status="success",
            details={"rows_processed": rows, "cursor": cursor, "object_type": object_type},
            created_at=now_ts,
        )
        con.commit()
    except Exception:
        con.rollback()
        fail_ts = now_iso()
        con.execute("BEGIN")
        try:
            upsert_sync_state(
                con,
                source=source,
                object_type=object_type,
                cursor=cursor,
                etag=None,
                status="error",
                rows_processed=0,
                last_synced_at=fail_ts,
                last_error="ingest_failed",
            )
            write_audit_log(
                con,
                event_type="catalog_ingest",
                source=source,
                status="error",
                details={"rows_processed": 0, "cursor": cursor, "object_type": object_type},
                created_at=fail_ts,
            )
            con.commit()
        except Exception:
            con.rollback()
        raise
    return rows


def bootstrap_bulk_file(
    con: sqlite3.Connection,
    *,
    bulk_type: str = "default_cards",
    bulk_download_uri: str | None = None,
) -> int:
    now_ts = now_iso()
    source = f"scryfall.bulk.{bulk_type}"
    if bulk_download_uri:
        download_uri = bulk_download_uri
        cursor = None
    else:
        meta_payload = _http_get_json(SCRYFALL_BULK_ENDPOINT)
        bulk_meta = _select_bulk_meta(meta_payload, bulk_type)
        download_uri = str(bulk_meta.get("download_uri") or "").strip()
        if not download_uri:
            raise ValueError("Bulk metadata missing download_uri")
        cursor = str(bulk_meta.get("updated_at") or "")

    cards_payload = _http_get_json(download_uri, timeout=120.0)
    cards = _iter_cards_payload(cards_payload)
    return _ingest_cards_transaction(
        con,
        cards=cards,
        source=source,
        cursor=cursor,
        now_ts=now_ts,
        object_type="bulk_file",
    )


def fetch_remote_set_codes() -> list[str]:
    payload = _http_get_json(SCRYFALL_SETS_ENDPOINT)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    codes: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip().lower()
        if code:
            codes.append(code)
    return sorted(set(codes))


def ingest_set_delta(con: sqlite3.Connection, *, set_code: str) -> int:
    normalized = set_code.strip().lower()
    if not normalized:
        return 0

    url = SCRYFALL_SET_PRINTS_ENDPOINT.format(set_code=normalized)
    cards: list[dict[str, Any]] = []
    while url:
        payload = _http_get_json(url)
        batch = _iter_cards_payload(payload)
        cards.extend(batch)
        if isinstance(payload, dict) and payload.get("has_more"):
            url = str(payload.get("next_page") or "").strip()
            if not url:
                break
        else:
            break

    return _ingest_cards_transaction(
        con,
        cards=cards,
        source=f"scryfall.set.{normalized}",
        cursor=None,
        now_ts=now_iso(),
        object_type="set_delta",
    )


async def startup_set_delta_check(get_con) -> None:
    if os.environ.get("TALENCE_DISABLE_STARTUP_SET_CHECK", "0") == "1":
        return
    try:
        remote_codes = fetch_remote_set_codes()
    except Exception:
        return

    con = get_con()
    try:
        rows = con.execute("SELECT set_code FROM catalog_sets").fetchall()
        local_codes = {
            str(row["set_code"]).strip().lower()
            for row in rows
            if row["set_code"] is not None
        }
        new_codes = sorted(set(remote_codes) - local_codes)
        for code in new_codes:
            try:
                ingest_set_delta(con, set_code=code)
            except Exception:
                # Startup set-check is best-effort and must not block boot.
                continue
    finally:
        con.close()


def schedule_startup_set_delta_check(get_con):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    return loop.create_task(startup_set_delta_check(get_con))
