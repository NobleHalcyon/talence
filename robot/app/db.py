from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


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


def init_db(con: sqlite3.Connection) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    con.executescript(sql)
    con.commit()