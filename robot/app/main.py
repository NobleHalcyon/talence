from __future__ import annotations
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import uuid

from talence_shared.sort_spec import SortSpec, OperatorConfig, Operator
from talence_shared.planner.plan import (
    CardInstance, SystemBins, BinCapacity, generate_plan
)

app = FastAPI(title="Talence Robot Service")

# In-memory stub for v1 skeleton (replace with SQLite in Milestone 1)
RUNS: Dict[str, Dict[str, Any]] = {}

class CreateLocalRunRequest(BaseModel):
    input_bin: int = 1
    unrecognized_bin: int = 35
    bins: List[int] = list(range(1, 36))
    capacities: Dict[int, int] = {i: 200 for i in range(1, 36)}  # placeholder

    operators: List[Dict[str, Any]]  # list of operator configs

class CreateLocalRunResponse(BaseModel):
    run_id: str

@app.get("/status")
def status():
    return {"status": "ok", "active_runs": len(RUNS)}

@app.post("/runs/create_local", response_model=CreateLocalRunResponse)
def create_local_run(req: CreateLocalRunRequest):
    run_id = str(uuid.uuid4())
    RUNS[run_id] = {
        "system_bins": {"input": req.input_bin, "unrec": req.unrecognized_bin},
        "bins": req.bins,
        "capacities": req.capacities,
        "operators": req.operators,
        "cards": [],  # CardInstance dicts
        "plan": None,
    }
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
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    instance_id = str(uuid.uuid4())
    run["cards"].append({
        "instance_id": instance_id,
        "name": req.name,
        "oracle_id": req.oracle_id,
        "print_id": req.print_id,
        "identified": req.identified,
        "current_bin": req.current_bin,
        "attrs": req.attrs,
    })
    return {"instance_id": instance_id}

@app.post("/runs/{run_id}/plan")
def plan(run_id: str):
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    # Build SortSpec
    op_cfgs = []
    for o in run["operators"]:
        op_cfgs.append(OperatorConfig(
            op=Operator(o["op"]),
            enabled=o.get("enabled", True),
            order=o.get("order", 0),
            deep=o.get("deep", False),
            split_into_bins=o.get("split_into_bins", False),
        ))
    spec = SortSpec(operators=op_cfgs)

    cards = [CardInstance(**c) for c in run["cards"]]
    sys_bins = SystemBins(input_bin=run["system_bins"]["input"], unrecognized_bin=run["system_bins"]["unrec"])
    caps = BinCapacity(capacity_by_bin={int(k): int(v) for k, v in run["capacities"].items()})
    all_bins = [int(b) for b in run["bins"]]

    mp = generate_plan(cards, spec, sys_bins, caps, all_bins)
    run["plan"] = mp
    return {
        "dest_sequences": mp.dest_sequences,
        "moves": [m.__dict__ for m in mp.moves],
        "notes": mp.notes,
    }
