# Talence QA Index

M0:
- scripts/qa/m0.ps1
  Validates:
  - Auth issuance
  - Refresh rotation
  - Run → Plan → Persist
  - FK enforcement
  - WAL mode
  - Persistence presence

M1:
- Automated:
  - `python -m pytest -q`
    Validates:
    - Lifecycle FSM transitions and trap/reset behavior
    - DB status constraints and failure fields
    - One-active-run enforcement
    - Startup resume-detection logging (no mutation)
    - Deterministic planner behavior (split/pinned/unrecognized semantics)
    - Execution stop/resume event persistence behavior
- Manual:
  - Follow `docs/dev-logs/TAL-M1-deterministic-robot-runtime.md` manual test steps

CI must pass for ratification.
