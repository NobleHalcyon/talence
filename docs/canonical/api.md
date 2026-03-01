# Talence API Contract

Version: Inherits Canonical

## 1. Robot Operations API

Authenticated endpoints for robotic execution context.

Current (M1):

- POST /runs/create_local
- POST /runs/{run_id}/start_scanning
- POST /runs/{run_id}/holding_ready
- POST /runs/{run_id}/debug_add_card
- POST /runs/{run_id}/plan
- POST /runs/{run_id}/fail
- POST /runs/{run_id}/reset_failed

Run lifecycle constraints (binding):

- Allowed status values:
  IDLE, SCANNING, HOLDING_READY, PLANNED, EXECUTING, COMPLETE, FAILED

- Deterministic transitions only (explicit and persisted).
- One active run per user (non-terminal = not COMPLETE/FAILED).
- FAILED is a trap state; requires explicit reset (reset_failed) to return to IDLE.
- On service startup, runs in SCANNING/HOLDING_READY/PLANNED/EXECUTING are detected and logged as resume-required; no auto-reset.

Future:
- POST /runs/{run_id}/execute
- POST /runs/{run_id}/scan

Robot API is run-scoped.

---

## 2. Collection API (Future M2)

Not run-scoped.

- POST /collection/cards
- GET /collection/cards
- POST /collection/pricing-refresh
- GET /collection/analytics

Collection endpoints must remain logically separate from robotic execution endpoints.

---

## 3. Pricing Behavior

During sort:
- Live price fetched once per print_id per run.
- Stored in run_price_snapshot.
- Also overwrites printings.price in DB.

Ensures:
- No mid-run price drift.
- Reduced duplicate API calls.