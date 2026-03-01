# TAL-M1 – Deterministic Robot Runtime

Thread Role: TALENCE / DEV / TAL-M1  
Branch: tal-m1-codex  
Canonical Version at Start: v0.7.0  
Touches Architecture: N

## Goal
Implement Milestone M1 end-to-end on the existing sqlite3 + FastAPI runtime, including canonical run lifecycle, restart-safe behavior, deterministic provisioning/planning persistence, and execution scaffolding with safe stop/resume.

## Definition of Done
- Canonical run FSM enforced in DB + API.
- One active run per user enforced on create.
- Startup resume detection logs active runs without mutation.
- Deterministic planner supports split-prefix provisioning, pinned bins, and unrecognized-bin exclusion.
- Execution scaffolding persists move events and supports stop/resume.
- Tests run without hardware and pass with `python -m pytest -q`.

## Implementation Summary
- Added lifecycle domain + service modules and routed lifecycle mutations through service-level guards.
- Migrated `runs` schema to canonical statuses and added failure/stop fields via runtime `init_db()` migration (no Alembic runtime dependency).
- Added lifecycle endpoints and centralized error mapping (`404` not found, `409` invalid transition/conflict).
- Added startup resume-required logging for active run states.
- Hardened planning with deterministic provisioning semantics: split-prefix grouping, contiguous virtual segment co-location, hard pinned-bin constraints, and split override for correctness when pin constraints exist.
- Added execute/stop endpoints with persisted `move_events`, deterministic resume from last `SUCCESS`, and standardized statuses (`SUCCESS`, `ERROR`, `STOPPED`).

## Files Changed
- `domain/run_constants.py`
- `domain/run_lifecycle.py`
- `services/run_service.py`
- `shared/talence_shared/planner/plan.py`
- `robot/app/schema.sql`
- `robot/app/db.py`
- `robot/app/main.py`
- `pytest.ini`
- `requirements.txt`
- `tests/test_run_lifecycle_fsm.py`
- `tests/test_run_lifecycle_db.py`
- `tests/test_run_snapshot_immutability.py`
- `tests/test_move_event_status_constants.py`
- `tests/test_run_lifecycle_api.py`
- `tests/test_resume_detection.py`
- `tests/test_planner_phase4.py`
- `tests/test_execution_api.py`

## Dependencies Added
- `pytest==9.0.2`
- `httpx==0.28.1`

## Schema Changes
- `runs.status` constrained to:
  - `IDLE`, `SCANNING`, `HOLDING_READY`, `PLANNED`, `EXECUTING`, `COMPLETE`, `FAILED`
- Added `runs.failed_code`
- Added `runs.failed_message`
- Added `runs.stop_requested` (`0/1`)
- Runtime migration in `init_db()` rebuilds legacy `runs` table shape and normalizes legacy statuses.

## Endpoints Added/Modified
- Added:
  - `POST /runs/{run_id}/start_scanning`
  - `POST /runs/{run_id}/holding_ready`
  - `POST /runs/{run_id}/fail`
  - `POST /runs/{run_id}/reset_failed`
  - `POST /runs/{run_id}/execute`
  - `POST /runs/{run_id}/stop`
- Modified:
  - `POST /runs/create_local` (initial `IDLE`, one-active-run enforcement)
  - `POST /runs/{run_id}/plan` (service-enforced transition to `PLANNED`)

## Migration Required
Y

## Manual Test Steps
1. Set env:
   - `set TALENCE_JWT_SECRET=<32+ char secret>`
   - `set PYTHONPATH=%CD%\shared`
2. Start app:
   - `python -m uvicorn robot.app.main:app --reload --port 8001`
3. Register/login and capture bearer token.
4. Create run:
   - `POST /runs/create_local` (expect `run_id`, status `IDLE` in DB).
5. Transition lifecycle:
   - `POST /start_scanning` -> `SCANNING`
   - `POST /holding_ready` -> `HOLDING_READY`
6. Add cards:
   - `POST /debug_add_card` (optionally include `attrs.pinned_bin`).
7. Plan:
   - `POST /plan` -> `PLANNED`, plan + moves persisted.
8. Execute/stop/resume:
   - `POST /execute` (writes `SUCCESS` move events)
   - `POST /stop` (writes `STOPPED`, clears stop flag, status `PLANNED`)
   - `POST /execute` again resumes from last success and completes.
9. Failure path:
   - `POST /fail` persists failure details and status `FAILED`
   - `POST /reset_failed` clears fields and returns to `IDLE`.
10. Restart app and confirm resume-required warnings for active statuses.

## Result
M1 runtime surfaces implemented with deterministic behavior, restart safety, and passing hardware-free test suite.

## Canonical Impact
None
