from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from talence.db.session import get_db  # adjust
from talence.domain.run_lifecycle import RunStatus, InvalidTransition
from talence.services.run_service import (
    set_status,
    fail_run,
    reset_failed_run,
    assert_no_active_run,
    ActiveRunExists,
    RunNotFound,
)

router = APIRouter(prefix="/runs", tags=["runs"])

@router.post("/start")
def start_run(db: Session = Depends(get_db), user_id: int = 1):  # replace with auth-derived user
    try:
        assert_no_active_run(db, user_id)
    except ActiveRunExists as e:
        raise HTTPException(status_code=409, detail=str(e))

    # create your Run row here (status=IDLE or directly SCANNING depending on your flow)
    # IMPORTANT: if "start" means entering SCANNING, do it explicitly:
    # - insert run (IDLE)
    # - set_status(run.id, SCANNING)
    # Return run_id, status

@router.post("/{run_id}/transition/{nxt}")
def transition(run_id: int, nxt: RunStatus, db: Session = Depends(get_db)):
    try:
        set_status(db, run_id, nxt)
        return {"run_id": run_id, "status": nxt.value}
    except RunNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidTransition as e:
        raise HTTPException(status_code=409, detail=str(e))

@router.post("/{run_id}/fail")
def fail(run_id: int, code: str | None = None, message: str | None = None, db: Session = Depends(get_db)):
    try:
        fail_run(db, run_id, code, message)
        return {"run_id": run_id, "status": RunStatus.FAILED.value}
    except RunNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidTransition as e:
        raise HTTPException(status_code=409, detail=str(e))

@router.post("/{run_id}/reset")
def reset(run_id: int, db: Session = Depends(get_db)):
    try:
        reset_failed_run(db, run_id)
        return {"run_id": run_id, "status": RunStatus.IDLE.value}
    except RunNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidTransition as e:
        raise HTTPException(status_code=409, detail=str(e))