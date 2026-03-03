from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_audit_log(
    con: sqlite3.Connection,
    *,
    event_type: str,
    source: str,
    status: str,
    details: dict[str, Any],
    created_at: str | None = None,
) -> None:
    con.execute(
        """
        INSERT INTO catalog_audit_log (event_type, source, status, details_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            event_type,
            source,
            status,
            json.dumps(details, separators=(",", ":"), sort_keys=True),
            created_at or now_iso(),
        ),
    )
