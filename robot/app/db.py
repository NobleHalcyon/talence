from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_CANONICAL_RUN_STATUSES = (
    "IDLE",
    "SCANNING",
    "HOLDING_READY",
    "PLANNED",
    "EXECUTING",
    "COMPLETE",
    "FAILED",
)


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


def _runs_table_exists(con: sqlite3.Connection) -> bool:
    row = con.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = 'runs'
        """
    ).fetchone()
    return row is not None


def _runs_columns(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("PRAGMA table_info(runs)").fetchall()
    return {str(r["name"]) for r in rows}


def _runs_create_sql(con: sqlite3.Connection) -> str:
    row = con.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'runs'
        """
    ).fetchone()
    return str(row["sql"] or "") if row else ""


def _has_canonical_status_check(create_sql: str) -> bool:
    normalized = "".join(create_sql.upper().split())
    expected = (
        "CHECK(STATUSIN('IDLE','SCANNING','HOLDING_READY','PLANNED',"
        "'EXECUTING','COMPLETE','FAILED'))"
    )
    return expected in normalized


def _requires_runs_rebuild(con: sqlite3.Connection) -> bool:
    required_columns = {
        "id",
        "user_id",
        "collection_id",
        "status",
        "input_bin_id",
        "unrecognized_bin_id",
        "purge_sort_enabled",
        "bins_json",
        "capacities_json",
        "operators_json",
        "failed_code",
        "failed_message",
        "stop_requested",
        "created_at",
        "updated_at",
    }
    columns = _runs_columns(con)
    if not required_columns.issubset(columns):
        return True
    return not _has_canonical_status_check(_runs_create_sql(con))


def _normalize_status_expr(columns: set[str]) -> str:
    if "status" not in columns:
        return "'IDLE' AS status"
    allowed = ",".join(f"'{s}'" for s in _CANONICAL_RUN_STATUSES)
    return (
        "CASE "
        "WHEN status IS NULL THEN 'IDLE' "
        "WHEN UPPER(TRIM(status)) = 'CREATED' THEN 'IDLE' "
        "WHEN UPPER(TRIM(status)) = 'PLANNED' THEN 'PLANNED' "
        f"WHEN UPPER(TRIM(status)) IN ({allowed}) THEN UPPER(TRIM(status)) "
        "ELSE 'IDLE' END AS status"
    )


def _select_or_default(columns: set[str], name: str, default_expr: str) -> str:
    if name in columns:
        return name
    return f"{default_expr} AS {name}"


def _rebuild_runs_table(con: sqlite3.Connection) -> None:
    columns = _runs_columns(con)
    select_columns = [
        _select_or_default(columns, "id", "''"),
        _select_or_default(columns, "user_id", "''"),
        _select_or_default(columns, "collection_id", "''"),
        _normalize_status_expr(columns),
        _select_or_default(columns, "input_bin_id", "1"),
        _select_or_default(columns, "unrecognized_bin_id", "35"),
        _select_or_default(columns, "purge_sort_enabled", "0"),
        _select_or_default(columns, "bins_json", "'[]'"),
        _select_or_default(columns, "capacities_json", "'{}'"),
        _select_or_default(columns, "operators_json", "'[]'"),
        _select_or_default(columns, "failed_code", "NULL"),
        _select_or_default(columns, "failed_message", "NULL"),
        _select_or_default(columns, "stop_requested", "0"),
        _select_or_default(columns, "created_at", "CURRENT_TIMESTAMP"),
        _select_or_default(columns, "updated_at", "CURRENT_TIMESTAMP"),
    ]
    select_sql = ",\n          ".join(select_columns)

    con.execute("PRAGMA foreign_keys = OFF;")
    try:
        con.execute(
            """
            CREATE TABLE runs_new (
              id                  TEXT PRIMARY KEY,
              user_id             TEXT NOT NULL,
              collection_id       TEXT NOT NULL,
              status              TEXT NOT NULL
                                    CHECK (status IN (
                                      'IDLE',
                                      'SCANNING',
                                      'HOLDING_READY',
                                      'PLANNED',
                                      'EXECUTING',
                                      'COMPLETE',
                                      'FAILED'
                                    )),
              input_bin_id        INTEGER NOT NULL DEFAULT 1,
              unrecognized_bin_id INTEGER NOT NULL DEFAULT 35,
              purge_sort_enabled  INTEGER NOT NULL DEFAULT 0 CHECK (purge_sort_enabled IN (0,1)),
              bins_json           TEXT NOT NULL,
              capacities_json     TEXT NOT NULL,
              operators_json      TEXT NOT NULL,
              failed_code         TEXT,
              failed_message      TEXT,
              stop_requested      INTEGER NOT NULL DEFAULT 0 CHECK (stop_requested IN (0,1)),
              created_at          TEXT NOT NULL,
              updated_at          TEXT NOT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
              FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
            )
            """
        )
        con.execute(
            f"""
            INSERT INTO runs_new (
              id,
              user_id,
              collection_id,
              status,
              input_bin_id,
              unrecognized_bin_id,
              purge_sort_enabled,
              bins_json,
              capacities_json,
              operators_json,
              failed_code,
              failed_message,
              stop_requested,
              created_at,
              updated_at
            )
            SELECT
              {select_sql}
            FROM runs
            """
        )
        con.execute("DROP TABLE runs")
        con.execute("ALTER TABLE runs_new RENAME TO runs")
        con.execute("CREATE INDEX IF NOT EXISTS idx_runs_user_status ON runs(user_id, status)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_runs_collection ON runs(collection_id)")
    finally:
        con.execute("PRAGMA foreign_keys = ON;")


def _migrate_runs_schema(con: sqlite3.Connection) -> None:
    if not _runs_table_exists(con):
        return
    if not _requires_runs_rebuild(con):
        return
    _rebuild_runs_table(con)


def init_db(con: sqlite3.Connection) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    con.executescript(sql)
    _migrate_runs_schema(con)
    con.commit()
