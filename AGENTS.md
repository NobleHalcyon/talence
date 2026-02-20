# Talence: Agent Instructions

## Non-negotiables
- Bins are LIFO stacks. A move is pop(source)->push(dest).
- Sorting is Scan -> Plan -> Execute. Never stream-sort into final bins.
- Correct final order beats bin utilization and move count.
- System bins exist and are configurable:
  - Input bin (default 1)
  - Unrecognized bin (default 35)
- Unrecognized bin is never used for staging.
- Sorting uses an aggregate composite key across enabled operators in order.
- Alphabetical deep sort uses full name ordering (not just first letter buckets).

## Development rules
- Prefer small, reviewable PRs.
- Add/adjust tests for planner logic.
- Don’t commit secrets, local DBs, or .venv.
- Keep Windows compatibility (cmd.exe friendly commands).
- If you change public APIs or DB schema, update SPEC/ARCHITECTURE notes.

## How to run locally (Windows cmd)
- Activate venv: .\.venv\Scripts\activate
- Set PYTHONPATH: set PYTHONPATH=%CD%\shared
- Run server: python -m uvicorn robot.app.main:app --reload --port 8001