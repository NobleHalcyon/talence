PRAGMA foreign_keys = ON;

-- =========================
-- Identity (required soon)
-- =========================
CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE,
  handle        TEXT UNIQUE,
  password_hash TEXT NOT NULL,
  is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  id                 TEXT PRIMARY KEY,
  user_id            TEXT NOT NULL,
  refresh_token_hash TEXT NOT NULL,
  created_at         TEXT NOT NULL,
  last_used_at       TEXT NOT NULL,
  expires_at         TEXT NOT NULL,
  revoked_at         TEXT,
  user_agent         TEXT,
  ip                 TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_revoked
  ON auth_sessions(user_id, revoked_at);

-- =========================
-- Foundation (single-game in V1)
-- =========================
CREATE TABLE IF NOT EXISTS games (
  id         TEXT PRIMARY KEY,
  code       TEXT NOT NULL UNIQUE,
  name       TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collections (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL,
  game_id    TEXT NOT NULL,
  name       TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
);

-- =========================
-- Runs (M1 lifecycle spine)
-- =========================
CREATE TABLE IF NOT EXISTS runs (
  id                  TEXT PRIMARY KEY,
  user_id             TEXT NOT NULL,
  collection_id       TEXT NOT NULL,

  status              TEXT NOT NULL CHECK (
    status IN ('IDLE','SCANNING','HOLDING_READY','PLANNED','EXECUTING','COMPLETE','FAILED')
  ),

  failed_code         TEXT,
  failed_message      TEXT,

  input_bin_id        INTEGER NOT NULL DEFAULT 1,
  unrecognized_bin_id INTEGER NOT NULL DEFAULT 35,
  purge_sort_enabled  INTEGER NOT NULL DEFAULT 0 CHECK (purge_sort_enabled IN (0,1)),

  bins_json           TEXT NOT NULL,
  capacities_json     TEXT NOT NULL,
  operators_json      TEXT NOT NULL,

  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,

  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
);

-- =========================
-- Run cards + planning
-- =========================
CREATE TABLE IF NOT EXISTS run_cards (
  instance_id TEXT PRIMARY KEY,
  run_id      TEXT NOT NULL,
  name        TEXT NOT NULL,
  oracle_id   TEXT NOT NULL,
  print_id    TEXT NOT NULL,
  identified  INTEGER NOT NULL DEFAULT 1 CHECK (identified IN (0,1)),
  current_bin INTEGER NOT NULL,
  attrs_json  TEXT NOT NULL DEFAULT '{}',
  created_at  TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS movement_plans (
  id                 TEXT PRIMARY KEY,
  run_id             TEXT NOT NULL,
  planner_version    TEXT NOT NULL,
  dest_sequences_json TEXT NOT NULL,
  notes_json         TEXT NOT NULL,
  created_at         TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planned_moves (
  id          TEXT PRIMARY KEY,
  plan_id     TEXT NOT NULL,
  step_no     INTEGER NOT NULL,
  from_bin    INTEGER NOT NULL,
  to_bin      INTEGER NOT NULL,
  instance_id TEXT,
  move_type   TEXT NOT NULL,
  notes       TEXT,
  FOREIGN KEY (plan_id) REFERENCES movement_plans(id) ON DELETE CASCADE
);