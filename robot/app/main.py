from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List
import uuid
import json
from datetime import datetime, timezone

from talence_shared.sort_spec import SortSpec, OperatorConfig, Operator
from talence_shared.planner.plan import (
    CardInstance, SystemBins, BinCapacity, generate_plan
)

from robot.app.db import connect, init_db

app = FastAPI(title="Talence Robot Service")

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def get_con():
    con = connect()
    init_db(con)
    return con

def ensure_seed(con) -> tuple[str, str, str]:
    """
    Seed a single dev user + MTG game + default collection.
    Auth comes next; this is just to make runs scorable and future-proof.
    """
    user_id = "dev-user"
    game_id = "game-mtg"
    collection_id = "col-default-mtg"

    ts = now_iso()

    con.execute(
        """
        INSERT OR IGNORE INTO users (id, email, handle, password_hash, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        """,
        (user_id, "dev@local", "dev", "DEV_PASSWORD_HASH_PLACEHOLDER", ts, ts),
    )

    con.execute(
        """
        INSERT OR IGNORE INTO games (id, code, name, created_at)
        VALUES (?, 'mtg', 'Magic: The Gathering', ?)
        """,
        (game_id, ts),
    )

    con.execute(
        """
        INSERT OR IGNORE INTO collections (id, user_id, game_id, name, created_at)
        VALUES (?, ?, ?, 'Default MTG Collection', ?)
        """,
        (collection_id, user_id, game_id, ts),
    )

    con.commit()
    return user_id, game_id, collection_id


class CreateLocalRunRequest(BaseModel):
    input_bin: int = 1
    unrecognized_bin: int = 35
    bins: List[int] = list(range(1, 36))
    capacities: Dict[int, int] = {i: 200 for i in range(1, 36)}  # placeholder
    operators: List[Dict[str, Any]]  # list of operator configs
    purge_sort_enabled: bool = False


class CreateLocalRunResponse(BaseModel):
    run_id: str


@app.get("/status")
def status():
    con = get_con()
    ensure_seed(con)
    row = con.execute("SELECT COUNT(*) AS n FROM runs").fetchone()
    return {"status": "ok", "runs_total": int(row["n"])}


@app.post("/runs/create_local", response_model=CreateLocalRunResponse)
def create_local_run(req: CreateLocalRunRequest):
    con = get_con()
    user_id, _, collection_id = ensure_seed(con)

    run_id = str(uuid.uuid4())
    ts = now_iso()

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
            run_id, user_id, collection_id, "created",
            req.input_bin, req.unrecognized_bin, 1 if req.purge_sort_enabled else 0,
            json.dumps(req.bins),
            json.dumps(req.capacities),
            json.dumps(req.operators),
            ts, ts
        )
    )
    con.commit()
    return CreateLocalRunResponse(run_id=run_id)


class AddCardRequest(BaseModel):
    name: str
    oracle_id: str
    print_id: str
    identified: bool = True
    current_bin: int
    attrs: Dict[str, Any] = {}


@app.post("/runs/{run_id}/debug_add_card")
def debug_add_card(run_id: str, req: AddCardRequest):
    con = get_con()
    ensure_seed(con)

    run = con.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not run:
        raise HTTPException(404, "Run not found")

    instance_id = str(uuid.uuid4())
    con.execute(
        """
        INSERT INTO run_cards (
          instance_id, run_id, name, oracle_id, print_id, identified, current_bin, attrs_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            instance_id, run_id, req.name, req.oracle_id, req.print_id,
            1 if req.identified else 0,
            req.current_bin,
            json.dumps(req.attrs),
            now_iso()
        )
    )
    con.commit()
    return {"instance_id": instance_id}


@app.post("/runs/{run_id}/plan")
def plan(run_id: str):
    con = get_con()
    ensure_seed(con)

    run = con.execute(
        "SELECT * FROM runs WHERE id = ?",
        (run_id,)
    ).fetchone()
    if not run:
        raise HTTPException(404, "Run not found")

    operators = json.loads(run["operators_json"])
    op_cfgs = []
    for o in operators:
        op_cfgs.append(OperatorConfig(
            op=Operator(o["op"]),
            enabled=o.get("enabled", True),
            order=o.get("order", 0),
            deep=o.get("deep", False),
            split_into_bins=o.get("split_into_bins", False),
        ))
    spec = SortSpec(operators=op_cfgs)

    card_rows = con.execute(
        "SELECT * FROM run_cards WHERE run_id = ? ORDER BY created_at ASC",
        (run_id,)
    ).fetchall()

    cards = []
    for r in card_rows:
        cards.append(CardInstance(
            instance_id=r["instance_id"],
            name=r["name"],
            oracle_id=r["oracle_id"],
            print_id=r["print_id"],
            identified=bool(r["identified"]),
            current_bin=int(r["current_bin"]),
            attrs=json.loads(r["attrs_json"]),
        ))

    sys_bins = SystemBins(input_bin=int(run["input_bin_id"]), unrecognized_bin=int(run["unrecognized_bin_id"]))
    caps = BinCapacity(capacity_by_bin={int(k): int(v) for k, v in json.loads(run["capacities_json"]).items()})
    all_bins = [int(b) for b in json.loads(run["bins_json"])]

    mp = generate_plan(cards, spec, sys_bins, caps, all_bins)

    # Persist plan
    plan_id = str(uuid.uuid4())
    con.execute(
        """
        INSERT INTO movement_plans (id, run_id, planner_version, dest_sequences_json, notes_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            plan_id, run_id, "v1",
            json.dumps(mp.dest_sequences),
            json.dumps(mp.notes),
            now_iso()
        )
    )

    # Persist moves
    for i, m in enumerate(mp.moves):
        move_id = str(uuid.uuid4())
        m_dict = m.__dict__.copy()
        instance_id = m_dict.get("instance_id") or m_dict.get("card_instance_id")  # tolerate either field name
        con.execute(
            """
            INSERT INTO planned_moves (id, plan_id, step_no, from_bin, to_bin, instance_id, move_type, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                move_id, plan_id, i,
                int(m.from_bin), int(m.to_bin),
                instance_id,
                "transfer",
                None
            )
        )

    con.execute("UPDATE runs SET status = ?, updated_at = ? WHERE id = ?", ("planned", now_iso(), run_id))
    con.commit()

    return {
        "dest_sequences": mp.dest_sequences,
        "moves": [m.__dict__ for m in mp.moves],
        "notes": mp.notes,
        "plan_id": plan_id,
    }