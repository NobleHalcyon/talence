# Talence API Contract

Version: Inherits Canonical

---

## 1. Auth and Robot Runtime (M1)

Authenticated endpoints:
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `POST /runs/create_local`
- `POST /runs/{run_id}/start_scanning`
- `POST /runs/{run_id}/holding_ready`
- `POST /runs/{run_id}/debug_add_card`
- `POST /runs/{run_id}/plan`
- `POST /runs/{run_id}/execute`
- `POST /runs/{run_id}/stop`
- `POST /runs/{run_id}/fail`
- `POST /runs/{run_id}/reset_failed`

Lifecycle constraints:
- Statuses are fixed: `IDLE`, `SCANNING`, `HOLDING_READY`, `PLANNED`, `EXECUTING`, `COMPLETE`, `FAILED`.
- One active run per user.
- Transitions are explicit and persisted.
- Startup may detect resume-required runs but must not mutate lifecycle state.

---

## 2. Catalog and Collection Endpoints (M2)

- `POST /catalog/bootstrap`
  - Explicit bootstrap ingest from Scryfall bulk source.
  - Idempotent with upsert semantics.

- `POST /catalog/images/cache`
  - Cache image by `(print_id, face_key)`.
  - Writes hash-sharded file and `print_face_images` metadata.

- `POST /runs/{run_id}/consolidate_collection`
  - Folds `run_cards` into `collection_cards`.
  - Uses `collection_consolidations` ledger for idempotency.

---

## 3. Pricing and Snapshot Behavior

During scan/planning flow:
- Price lookup is cached in-memory per run and print.
- `prices_current` stores latest mutable value.
- On transition to `PLANNED`, snapshot is captured in `run_price_snapshots`.
- Planning is blocked if snapshot cannot be fully captured.

Determinism rule:
- Once snapshot exists, run behavior must reference snapshot-only values.
- Later changes in `prices_current` must not alter an existing run snapshot.

---

## 4. Idempotency Rules

- `POST /catalog/bootstrap`:
  - Safe to rerun; same records update via conflict upsert.

- `POST /catalog/images/cache`:
  - Safe to rerun for same `(print_id, face_key)`; metadata row updates.

- `POST /runs/{run_id}/consolidate_collection`:
  - First call applies quantity fold + ledger insert.
  - Repeated calls are no-op and must not double-add.
