from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from talence_shared.planner.plan import BinCapacity, CardInstance, SystemBins, generate_plan
from talence_shared.sort_spec import Operator, OperatorConfig, SortSpec

from robot.app.db import connect, init_db
from robot.app.auth import (
    create_access_token,
    create_refresh_session,
    get_current_user,
    hash_password,
    rotate_refresh_session,
    revoke_refresh_session,
    verify_password,
)

log = logging.getLogger("talence")


# =========================
# Canonical Run Lifecycle (v0.6.0)
# =========================

class RunStatus:
    IDLE = "IDLE"
    SCANNING = "SCANNING"
    HOLDING_READY = "HOLDING_READY"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


ALLOWED_STATUSES = {
    RunStatus.IDLE,
    RunStatus.SCANNING,
    RunStatus.HOLDING_READY,
    RunStatus.PLANNED,
    RunStatus.EXECUTING,
    RunStatus.COMPLETE,
    RunStatus.FAILED,
}

TERMINAL_STATUSES = {RunStatus.COMPLETE, RunStatus.FAILED}

TRANSITIONS = {
    RunStatus.IDLE: {RunStatus.SCANNING},
    RunStatus.SCANNING: {RunStatus.HOLDING_READY, RunStatus.FAILED},
    RunStatus.HOLDING_READY: {RunStatus.PLANNED, RunStatus.FAILED},
    RunStatus.PLANNED: {RunStatus.EXECUTING, RunStatus.FAILED},
    RunStatus.EXECUTING: {RunStatus.COMPLETE, RunStatus.FAILED},
    RunStatus.COMPLETE: set(),
    RunStatus.FAILED: set(),  # trap state; explicit reset required
}


def assert_status_value(status: str) -> None:
    if status not in ALLOWED_STATUSES:
        raise HTTPException(500, f"Run has non-canonical status in DB: {status!r}")


def assert_transition(cur: str, nxt: str) -> None:
    assert_status_value(cur)
    assert_status_value(nxt)
    allowed = TRANSITIONS.get(cur, set())
    if nxt not in allowed:
        raise HTTPException(409, f"Invalid run transition: {cur} -> {nxt}")


def is_active(status: str) -> bool:
    assert_status_value(status)
    return status not in TERMINAL_STATUSES


def assert_can_reset_failed(cur: str) -> None:
    assert_status_value(cur)
    if cur != RunStatus.FAILED:
        raise HTTPException(409, f"Reset only allowed from FAILED, not {cur}")


# =========================
# Helpers
# =========================

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_con():
    con = connect()
    init_db(con)
    return con


def ensure_game_mtg(con) -> str:
    ts = now_iso()
    game_id = "game-mtg"
    con.execute(
        """
        INSERT OR IGNORE INTO games (id, code, name, created_at)
        VALUES (?, 'mtg', 'Magic: The Gathering', ?)
        """,
        (game_id, ts),
    )
    con.commit()
    return game_id


def ensure_default_collection(con, user_id: str) -> str:
    game_id = ensure_game_mtg(con)
    collection_id = f"col-default-{user_id}"
    con.execute(
        """
        INSERT OR IGNORE INTO collections (id, user_id, game_id, name, created_at)
        VALUES (?, ?, ?, 'Default MTG Collection', ?)
        """,
        (collection_id, user_id, game_id, now_iso()),
    )
    con.commit()
    return collection_id


def client_meta(req: Request) -> tuple[str | None, str | None]:
    ua = req.headers.get("user-agent")
    ip = req.client.host if req.client else None
    return ua, ip


def assert_no_active_run_for_user(con, user_id: str) -> None:
    row = con.execute(
        """
        SELECT id, status
        FROM runs
        WHERE user_id = ?
          AND status NOT IN ('COMPLETE', 'FAILED')
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()

    if row:
        assert_status_value(row["status"])
        raise HTTPException(409, f"Active run exists: {row['id']} ({row['status']})")


def assert_run_owner(con, run_id: str, user_id: str) -> dict:
    run = con.execute(
        "SELECT * FROM runs WHERE id = ? AND user_id = ?",
        (run_id, user_id),
    ).fetchone()
    if not run:
        raise HTTPException(404, "Run not found")
    assert_status_value(run["status"])
    return run


def set_run_status(con, run_id: str, nxt: str) -> None:
    run = con.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not run:
        raise HTTPException(404, "Run not found")
    cur = run["status"]
    assert_transition(cur, nxt)
    con.execute(
        "UPDATE runs SET status = ?, updated_at = ? WHERE id = ?",
        (nxt, now_iso(), run_id),
    )


def fail_run(con, run_id: str, code: str | None, message: str | None) -> None:
    run = con.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not run:
        raise HTTPException(404, "Run not found")

    cur = run["status"]
    assert_transition(cur, RunStatus.FAILED)

    con.execute(
        """
        UPDATE runs
        SET status = ?, failed_code = ?, failed_message = ?, updated_at = ?
        WHERE id = ?
        """,
        (RunStatus.FAILED, code, message, now_iso(), run_id),
    )


def reset_failed_run(con, run_id: str) -> None:
    run = con.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not run:
        raise HTTPException(404, "Run not found")

    cur = run["status"]
    assert_can_reset_failed(cur)

    con.execute(
        """
        UPDATE runs
        SET status = ?, failed_code = NULL, failed_message = NULL, updated_at = ?
        WHERE id = ?
        """,
        (RunStatus.IDLE, now_iso(), run_id),
    )


# =========================
# Lifespan (restart-safe resume detection)
# =========================

@asynccontextmanager
async def lifespan(app: FastAPI):
    con = get_con()
    rows = con.execute(
        """
        SELECT id, user_id, status
        FROM runs
        WHERE status IN ('SCANNING','HOLDING_READY','PLANNED','EXECUTING')
        """
    ).fetchall()

    for r in rows:
        assert_status_value(r["status"])
        log.warning(
            "RESUME REQUIRED: run_id=%s user_id=%s status=%s",
            r["id"], r["user_id"], r["status"],
        )

    yield


app = FastAPI(title="Talence Robot Service", lifespan=lifespan)


# =========================
# Models
# =========================

class CreateLocalRunRequest(BaseModel):
    input_bin: int = 1
    unrecognized_bin: int = 35
    bins: List[int] = list(range(1, 36))
    capacities: Dict[int, int] = {i: 200 for i in range(1, 36)}  # placeholder
    operators: List[Dict[str, Any]]  # list of operator configs
    purge_sort_enabled: bool = False


class CreateLocalRunResponse(BaseModel):
    run_id: str


class AddCardRequest(BaseModel):
    name: str
    oracle_id: str
    print_id: str
    identified: bool = True
    current_bin: int
    attrs: Dict[str, Any] = {}


class RegisterRequest(BaseModel):
    email: str
    password: str
    handle: str


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class FailRunRequest(BaseModel):
    failed_code: str | None = None
    failed_message: str | None = None


# =========================
# Routes
# =========================

@app.get("/status")
def status():
    return {"status": "ok"}


@app.get("/me/status")
def me_status(user=Depends(get_current_user)):
    con = get_con()
    row = con.execute(
        "SELECT COUNT(*) AS n FROM runs WHERE user_id = ?",
        (user["id"],),
    ).fetchone()
    return {"status": "ok", "runs_total": int(row["n"])}


@app.post("/auth/register")
def register(req: RegisterRequest, request: Request):
    con = get_con()
    ts = now_iso()
    email = req.email.strip().lower()
    handle = req.handle.strip()

    existing = con.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        raise HTTPException(400, "User already exists")

    user_id = str(uuid.uuid4())

    try:
        con.execute(
            """
            INSERT INTO users (id, email, handle, password_hash, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (user_id, email, handle, hash_password(req.password), ts, ts),
        )
        con.commit()
    except sqlite3.IntegrityError as e:
        raise HTTPException(400, f"Registration failed: {e}")
    except Exception as e:
        raise HTTPException(500, f"Registration error: {type(e).__name__}: {e}")

    ensure_default_collection(con, user_id)

    access_token = create_access_token(user_id)
    ua, ip = client_meta(request)
    sess = create_refresh_session(user_id=user_id, user_agent=ua, ip=ip)

    return {
        "access_token": access_token,
        "refresh_token": sess["refresh_token"],
        "refresh_expires_at": sess["expires_at"],
    }


@app.post("/auth/login")
def login(req: LoginRequest, request: Request):
    con = get_con()
    email = req.email.strip().lower()

    row = con.execute(
        "SELECT id, password_hash, is_active FROM users WHERE email = ?",
        (email,),
    ).fetchone()

    if not row or not row["is_active"]:
        raise HTTPException(401, "Invalid credentials")

    if not verify_password(req.password, row["password_hash"]):
        raise HTTPException(401, "Invalid credentials")

    ensure_default_collection(con, row["id"])

    access_token = create_access_token(row["id"])
    ua, ip = client_meta(request)
    sess = create_refresh_session(user_id=row["id"], user_agent=ua, ip=ip)

    return {
        "access_token": access_token,
        "refresh_token": sess["refresh_token"],
        "refresh_expires_at": sess["expires_at"],
    }


@app.post("/auth/refresh")
def refresh(req: RefreshRequest, request: Request):
    ua, ip = client_meta(request)
    rotated = rotate_refresh_session(refresh_token=req.refresh_token, user_agent=ua, ip=ip)
    access_token = create_access_token(rotated["user_id"])
    return {
        "access_token": access_token,
        "refresh_token": rotated["refresh_token"],
        "refresh_expires_at": rotated["expires_at"],
    }


@app.post("/auth/logout")
def logout(req: LogoutRequest):
    revoke_refresh_session(req.refresh_token)
    return {"ok": True}


@app.post("/runs/create_local", response_model=CreateLocalRunResponse)
def create_local_run(req: CreateLocalRunRequest, user=Depends(get_current_user)):
    con = get_con()
    user_id = user["id"]

    # Canonical: one active run per user
    assert_no_active_run_for_user(con, user_id)

    collection_id = ensure_default_collection(con, user_id)

    run_id = str(uuid.uuid4())
    ts = now_iso()

    # Canonical initial status
    con.execute(
        """
        INSERT INTO runs (
          id, user_id, collection_id, status,
          input_bin_id, unrecognized_bin_id, purge_sort_enabled,
          bins_json, capacities_json, operators_json,
          created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            user_id,
            collection_id,
            RunStatus.IDLE,
            req.input_bin,
            req.unrecognized_bin,
            1 if req.purge_sort_enabled else 0,
            json.dumps(req.bins),
            json.dumps(req.capacities),
            json.dumps(req.operators),
            ts,
            ts,
        ),
    )
    con.commit()
    return CreateLocalRunResponse(run_id=run_id)


@app.post("/runs/{run_id}/start_scanning")
def start_scanning(run_id: str, user=Depends(get_current_user)):
    con = get_con()
    assert_run_owner(con, run_id, user["id"])
    set_run_status(con, run_id, RunStatus.SCANNING)
    con.commit()
    return {"ok": True, "status": RunStatus.SCANNING}


@app.post("/runs/{run_id}/holding_ready")
def holding_ready(run_id: str, user=Depends(get_current_user)):
    con = get_con()
    assert_run_owner(con, run_id, user["id"])
    set_run_status(con, run_id, RunStatus.HOLDING_READY)
    con.commit()
    return {"ok": True, "status": RunStatus.HOLDING_READY}


@app.post("/runs/{run_id}/debug_add_card")
def debug_add_card(run_id: str, req: AddCardRequest, user=Depends(get_current_user)):
    con = get_con()
    assert_run_owner(con, run_id, user["id"])

    instance_id = str(uuid.uuid4())
    con.execute(
        """
        INSERT INTO run_cards (
          instance_id, run_id, name, oracle_id, print_id, identified, current_bin, attrs_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            instance_id,
            run_id,
            req.name,
            req.oracle_id,
            req.print_id,
            1 if req.identified else 0,
            req.current_bin,
            json.dumps(req.attrs),
            now_iso(),
        ),
    )
    con.commit()
    return {"instance_id": instance_id}


@app.post("/runs/{run_id}/fail")
def fail(run_id: str, req: FailRunRequest, user=Depends(get_current_user)):
    con = get_con()
    assert_run_owner(con, run_id, user["id"])

    fail_run(con, run_id, req.failed_code, req.failed_message)
    con.commit()
    return {"ok": True, "status": RunStatus.FAILED}


@app.post("/runs/{run_id}/reset_failed")
def reset_failed(run_id: str, user=Depends(get_current_user)):
    con = get_con()
    assert_run_owner(con, run_id, user["id"])

    reset_failed_run(con, run_id)
    con.commit()
    return {"ok": True, "status": RunStatus.IDLE}


@app.post("/runs/{run_id}/plan")
def plan(run_id: str, user=Depends(get_current_user)):
    con = get_con()
    run = assert_run_owner(con, run_id, user["id"])

    # Canonical: HOLDING_READY -> PLANNED
    assert_transition(run["status"], RunStatus.PLANNED)

    operators = json.loads(run["operators_json"])
    op_cfgs: List[OperatorConfig] = []
    for o in operators:
        op_cfgs.append(
            OperatorConfig(
                op=Operator(o["op"]),
                enabled=o.get("enabled", True),
                order=o.get("order", 0),
                deep=o.get("deep", False),
                split_into_bins=o.get("split_into_bins", False),
            )
        )
    spec = SortSpec(operators=op_cfgs)

    card_rows = con.execute(
        "SELECT * FROM run_cards WHERE run_id = ? ORDER BY created_at ASC",
        (run_id,),
    ).fetchall()

    cards: List[CardInstance] = []
    for r in card_rows:
        cards.append(
            CardInstance(
                instance_id=r["instance_id"],
                name=r["name"],
                oracle_id=r["oracle_id"],
                print_id=r["print_id"],
                identified=bool(r["identified"]),
                current_bin=int(r["current_bin"]),
                attrs=json.loads(r["attrs_json"]),
            )
        )

    sys_bins = SystemBins(
        input_bin=int(run["input_bin_id"]),
        unrecognized_bin=int(run["unrecognized_bin_id"]),
    )
    caps = BinCapacity(
        capacity_by_bin={int(k): int(v) for k, v in json.loads(run["capacities_json"]).items()}
    )
    all_bins = [int(b) for b in json.loads(run["bins_json"])]

    mp = generate_plan(cards, spec, sys_bins, caps, all_bins)

    plan_id = str(uuid.uuid4())
    con.execute(
        """
        INSERT INTO movement_plans (id, run_id, planner_version, dest_sequences_json, notes_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            plan_id,
            run_id,
            "v1",
            json.dumps(mp.dest_sequences),
            json.dumps(mp.notes),
            now_iso(),
        ),
    )

    for i, m in enumerate(mp.moves):
        move_id = str(uuid.uuid4())
        m_dict = m.__dict__.copy()
        instance_id = m_dict.get("instance_id") or m_dict.get("card_instance_id")

        con.execute(
            """
            INSERT INTO planned_moves (id, plan_id, step_no, from_bin, to_bin, instance_id, move_type, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                move_id,
                plan_id,
                i,
                int(m.from_bin),
                int(m.to_bin),
                instance_id,
                "transfer",
                None,
            ),
        )

    set_run_status(con, run_id, RunStatus.PLANNED)
    con.commit()

    return {
        "plan_id": plan_id,
        "dest_sequences": mp.dest_sequences,
        "moves": [m.__dict__ for m in mp.moves],
        "notes": mp.notes,
    }