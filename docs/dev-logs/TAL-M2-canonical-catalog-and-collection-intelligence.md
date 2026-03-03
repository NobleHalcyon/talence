# TAL-M2 Canonical Catalog and Collection Intelligence

Date: 2026-03-03
Branch: `tal-m2-codex`
Scope: Canonical M2 implementation

---

## Summary

Implemented M2 catalog and collection-intelligence foundations without mutating M0/M1 lifecycle semantics:

- Added additive M2 schema tables for catalog, pricing, images, and consolidation ledger.
- Added modular catalog package (`sync`, `upsert`, `pricing`, `images`, `audit`).
- Added explicit bootstrap ingest endpoint with upsert + audit/sync tracking.
- Added best-effort startup set check with non-blocking behavior.
- Added hash-sharded image cache persistence and metadata tracking.
- Added deterministic pricing snapshot capture at PLANNED with snapshot completeness guard.
- Added idempotent collection consolidation endpoint backed by ledger table.
- Added offline automated tests for all M2 behaviors.

---

## Schema Changes

Added tables:

- `catalog_sets`
- `catalog_prints`
- `sync_state`
- `catalog_audit_log`
- `prices_current`
- `run_price_snapshots`
- `print_face_images`
- `collection_cards`
- `collection_consolidations`

Added supporting indexes and conflict-upsert usage in runtime logic.

No mutation to existing M0/M1 run lifecycle states or transition rules.

---

## Manual Verification Steps

1. Activate environment and run API:
   - `.\.venv\Scripts\activate`
   - `set PYTHONPATH=%CD%\shared`
   - `python -m uvicorn robot.app.main:app --reload --port 8001`

2. Run full tests offline:
   - `.\.venv\Scripts\python.exe -m pytest -q`

3. Validate bootstrap ingest:
   - Call `POST /catalog/bootstrap` with auth token.
   - Confirm `catalog_prints`, `sync_state`, and `catalog_audit_log` rows.
   - Repeat call and confirm idempotent row counts.

4. Validate image cache:
   - Ensure print exists in `catalog_prints`.
   - Call `POST /catalog/images/cache`.
   - Confirm file path shape `data/images/xx/yy/{sha}.jpg`.
   - Confirm `print_face_images.phash IS NULL`.

5. Validate run price snapshot:
   - Create run, add cards, plan.
   - Confirm `run_price_snapshots` rows exist for all distinct run print_ids.
   - Update `prices_current` and verify snapshot rows do not change.

6. Validate consolidation idempotency:
   - Call `POST /runs/{run_id}/consolidate_collection` twice.
   - Confirm quantities update once and ledger row count remains one.

---

## Limitations

- Startup set-check remains best-effort and silently ignores network errors.
- Price fetch falls back to deterministic zero pricing when live lookup is unavailable.
- Perceptual hash (`phash`) pipeline is intentionally deferred beyond M2.
