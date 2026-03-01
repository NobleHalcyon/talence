from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

ALLOWED_STATUS = ("IDLE", "SCANNING", "HOLDING_READY", "PLANNED", "EXECUTING", "COMPLETE", "FAILED")


def get_db_path() -> Path:
    # Prefer env var, default to repo/data/talence_dev.db
    p = os.environ.get("TALENCE_DB_PATH")
    if p:
        return Path(p)
    # repo_root/robot/app/db.py -> repo_root
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "data" / "talence_dev.db"


def connect() -> sqlite3.Connection:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row

    # Pragmas: safe defaults for dev + robotics-style workloads
    con.execute("PRAGMA foreign_keys = ON;")
    con.execute("PRAGMA journal_mode = WAL;")
    con.execute("PRAGMA synchronous = NORMAL;")
    return con


def _column_exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    rows = con.execute(f"PRAGMA table_info({table});").fetchall()
    return any(r["name"] == column for r in rows)


def _runs_has_status_check(con: sqlite3.Connection) -> bool:
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='runs';"
    ).fetchone()
    if not row or not row["sql"]:
        return False
    sql = row["sql"].upper()
    # crude-but-effective check: must include CHECK and the canonical literals
    return (
        "CHECK" in sql
        and "STATUS" in sql
        and "IDLE" in sql
        and "SCANNING" in sql
        and "HOLDING_READY" in sql
        and "PLANNED" in sql
        and "EXECUTING" in sql
        and "COMPLETE" in sql
        and "FAILED" in sql
    )


def _normalize_run_statuses(con: sqlite3.Connection) -> None:
    allowed_list = ",".join([f"'{s}'" for s in ALLOWED_STATUS])
    con.execute(
        f"""
        UPDATE runs
        SET status='IDLE'
        WHERE status IS NULL OR status NOT IN ({allowed_list});
        """
    )


def _ensure_runs_m1(con: sqlite3.Connection) -> None:
    """
    Ensure runs table matches Canonical M1 lifecycle requirements:
    - status limited to allowed values via CHECK constraint
    - failed_code / failed_message columns exist
    - unknown statuses normalized to IDLE
    """
    # Add columns if missing (safe)
    if not _column_exists(con, "runs", "failed_code"):
        con.execute("ALTER TABLE runs ADD COLUMN failed_code TEXT;")
    if not _column_exists(con, "runs", "failed_message"):
        con.execute("ALTER TABLE runs ADD COLUMN failed_message TEXT;")

    _normalize_run_statuses(con)

    # If CHECK constraint missing, rebuild runs table (SQLite limitation)
    if not _runs_has_status_check(con):
        allowed_list = ",".join([f"'{s}'" for s in ALLOWED_STATUS])

        con.execute("BEGIN;")
        try:
            con.execute(
                f"""
                CREATE TABLE runs__new (
                  id                  TEXT PRIMARY KEY,
                  user_id             TEXT NOT NULL,
                  collection_id       TEXT NOT NULL,

                  status              TEXT NOT NULL CHECK (
                    status IN ({allowed_list})
                  ),

                  failed_code         TEXT,
                  failed_message      TEXT,

                  input_bin_id        INTEGER NOT NULL DEFAULT 1,
                  unrecognized_bin_id INTEGER NOT NULL DEFAULT 35,
                  purge_sort_enabled  INTEGER NOT NULL DEFAULT 0 CHECK (purge_sort_enabled IN (0,1)),

                  bins_json           TEXT NOT NULL,
                  capacities_json     TEXT NOT NULL,
                  operators_json      TEXT NOT NULL,

                  created_at          TEXT NOT NULL,
                  updated_at          TEXT NOT NULL,

                  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                  FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
                );
                """
            )

            con.execute(
                f"""
                INSERT INTO runs__new (
                  id, user_id, collection_id, status,
                  failed_code, failed_message,
                  input_bin_id, unrecognized_bin_id, purge_sort_enabled,
                  bins_json, capacities_json, operators_json,
                  created_at, updated_at
                )
                SELECT
                  id,
                  user_id,
                  collection_id,
                  CASE
                    WHEN status IN ({allowed_list}) THEN status
                    ELSE 'IDLE'
                  END AS status,
                  failed_code,
                  failed_message,
                  input_bin_id,
                  unrecognized_bin_id,
                  purge_sort_enabled,
                  bins_json,
                  capacities_json,
                  operators_json,
                  created_at,
                  updated_at
                FROM runs;
                """
            )

            con.execute("DROP TABLE runs;")
            con.execute("ALTER TABLE runs__new RENAME TO runs;")
            con.execute("COMMIT;")
        except Exception:
            con.execute("ROLLBACK;")
            raise


def init_db(con: sqlite3.Connection) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    con.executescript(sql)

    # M1 spine enforcement for runs table (idempotent)
    # This keeps dev DBs from drifting into non-canonical states.
    _ensure_runs_m1(con)

    con.commit()