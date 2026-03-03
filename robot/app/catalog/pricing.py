from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
import re
from typing import Any

import httpx

from robot.app.catalog.audit import now_iso


class MissingSnapshotPriceError(ValueError):
    pass


@dataclass(frozen=True)
class PricePoint:
    print_id: str
    price_usd_cents: int | None
    price_usd_foil_cents: int | None
    source: str
    fetched_at: str
    raw_json: str | None = None


_RUN_PRICE_CACHE: dict[str, dict[str, PricePoint]] = {}
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _usd_to_cents(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(str(value)) * 100))
    except (TypeError, ValueError):
        return None


def _fetch_live_price(print_id: str) -> PricePoint | None:
    if not print_id.strip():
        return None
    ts = now_iso()
    if not _UUID_RE.match(print_id):
        return PricePoint(
            print_id=print_id,
            price_usd_cents=0,
            price_usd_foil_cents=0,
            source="fallback_zero",
            fetched_at=ts,
            raw_json=None,
        )
    try:
        resp = httpx.get(f"https://api.scryfall.com/cards/{print_id}", timeout=30.0)
        resp.raise_for_status()
        payload = resp.json()
        prices = payload.get("prices") if isinstance(payload, dict) else {}
        if not isinstance(prices, dict):
            prices = {}
        return PricePoint(
            print_id=print_id,
            price_usd_cents=_usd_to_cents(prices.get("usd")),
            price_usd_foil_cents=_usd_to_cents(prices.get("usd_foil")),
            source="scryfall_live",
            fetched_at=ts,
            raw_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )
    except Exception:
        # Keep the runtime deterministic and offline-safe.
        return PricePoint(
            print_id=print_id,
            price_usd_cents=0,
            price_usd_foil_cents=0,
            source="fallback_zero",
            fetched_at=ts,
            raw_json=None,
        )


def _upsert_prices_current(con: sqlite3.Connection, price: PricePoint) -> None:
    con.execute(
        """
        INSERT INTO prices_current (
          print_id, price_usd_cents, price_usd_foil_cents, source, fetched_at, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(print_id) DO UPDATE SET
          price_usd_cents = excluded.price_usd_cents,
          price_usd_foil_cents = excluded.price_usd_foil_cents,
          source = excluded.source,
          fetched_at = excluded.fetched_at,
          raw_json = excluded.raw_json
        """,
        (
            price.print_id,
            price.price_usd_cents,
            price.price_usd_foil_cents,
            price.source,
            price.fetched_at,
            price.raw_json,
        ),
    )


def _load_current_price(con: sqlite3.Connection, print_id: str) -> PricePoint | None:
    row = con.execute(
        """
        SELECT print_id, price_usd_cents, price_usd_foil_cents, source, fetched_at, raw_json
        FROM prices_current
        WHERE print_id = ?
        """,
        (print_id,),
    ).fetchone()
    if not row:
        return None
    return PricePoint(
        print_id=str(row["print_id"]),
        price_usd_cents=row["price_usd_cents"],
        price_usd_foil_cents=row["price_usd_foil_cents"],
        source=str(row["source"]),
        fetched_at=str(row["fetched_at"]),
        raw_json=row["raw_json"],
    )


def ensure_price_for_run(con: sqlite3.Connection, *, run_id: str, print_id: str) -> PricePoint | None:
    run_cache = _RUN_PRICE_CACHE.setdefault(run_id, {})
    if print_id in run_cache:
        return run_cache[print_id]

    current = _load_current_price(con, print_id)
    if current is None:
        fetched = _fetch_live_price(print_id)
        if fetched is None:
            return None
        _upsert_prices_current(con, fetched)
        current = fetched

    run_cache[print_id] = current
    return current


def ensure_prices_for_run(con: sqlite3.Connection, *, run_id: str) -> dict[str, PricePoint]:
    rows = con.execute(
        "SELECT DISTINCT print_id FROM run_cards WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    for row in rows:
        pid = str(row["print_id"] or "")
        if not pid:
            continue
        ensure_price_for_run(con, run_id=run_id, print_id=pid)
    return dict(_RUN_PRICE_CACHE.get(run_id, {}))


def capture_run_price_snapshot(con: sqlite3.Connection, *, run_id: str) -> int:
    con.execute(
        """
        INSERT INTO run_price_snapshots (
          run_id, print_id, price_usd_cents, price_usd_foil_cents, source, fetched_at
        )
        SELECT ?, rc.print_id, pc.price_usd_cents, pc.price_usd_foil_cents, pc.source, pc.fetched_at
        FROM (SELECT DISTINCT print_id FROM run_cards WHERE run_id = ?) rc
        JOIN prices_current pc ON pc.print_id = rc.print_id
        ON CONFLICT(run_id, print_id) DO NOTHING
        """,
        (run_id, run_id),
    )

    total_prints = int(
        con.execute(
            "SELECT COUNT(DISTINCT print_id) AS n FROM run_cards WHERE run_id = ?",
            (run_id,),
        ).fetchone()["n"]
    )
    snap_count = int(
        con.execute(
            "SELECT COUNT(*) AS n FROM run_price_snapshots WHERE run_id = ?",
            (run_id,),
        ).fetchone()["n"]
    )
    if snap_count < total_prints:
        raise MissingSnapshotPriceError(
            f"snapshot incomplete for run {run_id}: expected {total_prints}, found {snap_count}"
        )

    null_prices = int(
        con.execute(
            """
            SELECT COUNT(*) AS n
            FROM run_price_snapshots
            WHERE run_id = ? AND price_usd_cents IS NULL AND price_usd_foil_cents IS NULL
            """,
            (run_id,),
        ).fetchone()["n"]
    )
    if null_prices > 0:
        raise MissingSnapshotPriceError(
            f"snapshot missing price values for {null_prices} print(s) in run {run_id}"
        )

    return snap_count


def load_run_snapshot(con: sqlite3.Connection, *, run_id: str) -> dict[str, PricePoint]:
    rows = con.execute(
        """
        SELECT print_id, price_usd_cents, price_usd_foil_cents, source, fetched_at
        FROM run_price_snapshots
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchall()
    return {
        str(row["print_id"]): PricePoint(
            print_id=str(row["print_id"]),
            price_usd_cents=row["price_usd_cents"],
            price_usd_foil_cents=row["price_usd_foil_cents"],
            source=str(row["source"]),
            fetched_at=str(row["fetched_at"]),
        )
        for row in rows
    }


def clear_run_price_cache(run_id: str) -> None:
    _RUN_PRICE_CACHE.pop(run_id, None)
