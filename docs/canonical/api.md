# Talence API Contract

Version: Inherits Canonical

## 1. Robot Operations API

Authenticated endpoints for robotic execution context.

- POST /runs/create_local
- POST /runs/{run_id}/debug_add_card
- POST /runs/{run_id}/plan

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