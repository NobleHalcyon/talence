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
  FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_collections_user_id ON collections(user_id);

-- =========================
-- Ops spine (runs/plans)
-- =========================
CREATE TABLE IF NOT EXISTS runs (
  id                  TEXT PRIMARY KEY,
  user_id             TEXT NOT NULL,
  collection_id       TEXT NOT NULL,
  status              TEXT NOT NULL
                        CHECK (status IN (
                          'IDLE',
                          'SCANNING',
                          'HOLDING_READY',
                          'PLANNED',
                          'EXECUTING',
                          'COMPLETE',
                          'FAILED'
                        )),
  input_bin_id        INTEGER NOT NULL DEFAULT 1,
  unrecognized_bin_id INTEGER NOT NULL DEFAULT 35,
  purge_sort_enabled  INTEGER NOT NULL DEFAULT 0 CHECK (purge_sort_enabled IN (0,1)),
  bins_json           TEXT NOT NULL,
  capacities_json     TEXT NOT NULL,
  operators_json      TEXT NOT NULL,
  failed_code         TEXT,
  failed_message      TEXT,
  stop_requested      INTEGER NOT NULL DEFAULT 0 CHECK (stop_requested IN (0,1)),
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runs_user_status ON runs(user_id, status);
CREATE INDEX IF NOT EXISTS idx_runs_collection ON runs(collection_id);

-- Run-scoped cards (this replaces the in-memory "cards" list)
CREATE TABLE IF NOT EXISTS run_cards (
  instance_id  TEXT PRIMARY KEY,
  run_id       TEXT NOT NULL,
  name         TEXT NOT NULL,
  oracle_id    TEXT NOT NULL,
  print_id     TEXT NOT NULL,
  identified   INTEGER NOT NULL CHECK (identified IN (0,1)),
  current_bin  INTEGER NOT NULL,
  attrs_json   TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_run_cards_run ON run_cards(run_id);

CREATE TABLE IF NOT EXISTS movement_plans (
  id             TEXT PRIMARY KEY,
  run_id         TEXT NOT NULL,
  planner_version TEXT NOT NULL,
  dest_sequences_json TEXT NOT NULL,
  notes_json     TEXT NOT NULL,
  created_at     TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_movement_plans_run ON movement_plans(run_id);

CREATE TABLE IF NOT EXISTS planned_moves (
  id            TEXT PRIMARY KEY,
  plan_id       TEXT NOT NULL,
  step_no       INTEGER NOT NULL,
  from_bin      INTEGER NOT NULL,
  to_bin        INTEGER NOT NULL,
  instance_id   TEXT,
  move_type     TEXT NOT NULL DEFAULT 'transfer',
  notes         TEXT,
  FOREIGN KEY (plan_id) REFERENCES movement_plans(id) ON DELETE CASCADE,
  FOREIGN KEY (instance_id) REFERENCES run_cards(instance_id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_planned_moves_plan_step
  ON planned_moves(plan_id, step_no);

-- Execution log (empty for now, but canonical)
CREATE TABLE IF NOT EXISTS move_events (
  id              TEXT PRIMARY KEY,
  plan_id          TEXT NOT NULL,
  step_no          INTEGER NOT NULL,
  timestamp        TEXT NOT NULL,
  from_bin         INTEGER,
  to_bin           INTEGER,
  instance_id      TEXT,
  status           TEXT NOT NULL,
  error            TEXT,
  hardware_txn_id  TEXT,
  FOREIGN KEY (plan_id) REFERENCES movement_plans(id) ON DELETE CASCADE,
  FOREIGN KEY (instance_id) REFERENCES run_cards(instance_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_move_events_plan_step ON move_events(plan_id, step_no);

-- =========================
-- M2 Catalog & Collection Intelligence (additive only)
-- =========================
CREATE TABLE IF NOT EXISTS catalog_sets (
  set_code        TEXT PRIMARY KEY,
  scryfall_set_id TEXT UNIQUE,
  name            TEXT NOT NULL,
  released_at     TEXT,
  set_type        TEXT,
  card_count      INTEGER,
  digital         INTEGER NOT NULL DEFAULT 0 CHECK (digital IN (0,1)),
  raw_json        TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_catalog_sets_released_at
  ON catalog_sets(released_at);

CREATE TABLE IF NOT EXISTS catalog_prints (
  print_id          TEXT PRIMARY KEY,
  oracle_id         TEXT,
  set_code          TEXT,
  name              TEXT NOT NULL,
  collector_number  TEXT,
  rarity            TEXT,
  lang              TEXT,
  image_small_url   TEXT,
  image_normal_url  TEXT,
  image_large_url   TEXT,
  scryfall_uri      TEXT,
  raw_json          TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  FOREIGN KEY (set_code) REFERENCES catalog_sets(set_code) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_catalog_prints_set_code
  ON catalog_prints(set_code);

CREATE INDEX IF NOT EXISTS idx_catalog_prints_oracle_id
  ON catalog_prints(oracle_id);

CREATE INDEX IF NOT EXISTS idx_catalog_prints_name
  ON catalog_prints(name);

CREATE TABLE IF NOT EXISTS sync_state (
  source          TEXT PRIMARY KEY,
  object_type     TEXT NOT NULL,
  cursor          TEXT,
  etag            TEXT,
  status          TEXT NOT NULL,
  rows_processed  INTEGER NOT NULL DEFAULT 0,
  last_synced_at  TEXT NOT NULL,
  last_error      TEXT
);

CREATE TABLE IF NOT EXISTS catalog_audit_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type    TEXT NOT NULL,
  source        TEXT NOT NULL,
  status        TEXT NOT NULL,
  details_json  TEXT NOT NULL,
  created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_catalog_audit_log_created_at
  ON catalog_audit_log(created_at);

CREATE TABLE IF NOT EXISTS prices_current (
  print_id               TEXT PRIMARY KEY,
  price_usd_cents        INTEGER,
  price_usd_foil_cents   INTEGER,
  source                 TEXT NOT NULL,
  fetched_at             TEXT NOT NULL,
  raw_json               TEXT
);

CREATE TABLE IF NOT EXISTS run_price_snapshots (
  run_id                 TEXT NOT NULL,
  print_id               TEXT NOT NULL,
  price_usd_cents        INTEGER,
  price_usd_foil_cents   INTEGER,
  source                 TEXT NOT NULL,
  fetched_at             TEXT NOT NULL,
  PRIMARY KEY (run_id, print_id),
  FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_run_price_snapshots_print_id
  ON run_price_snapshots(print_id);

CREATE TABLE IF NOT EXISTS print_face_images (
  id             TEXT PRIMARY KEY,
  print_id       TEXT NOT NULL,
  face_key       TEXT NOT NULL,
  source_url     TEXT NOT NULL,
  sha256         TEXT NOT NULL,
  local_path     TEXT NOT NULL,
  mime_type      TEXT,
  width          INTEGER,
  height         INTEGER,
  phash          TEXT,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL,
  UNIQUE (print_id, face_key),
  FOREIGN KEY (print_id) REFERENCES catalog_prints(print_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_print_face_images_print_id
  ON print_face_images(print_id);

CREATE TABLE IF NOT EXISTS collection_cards (
  collection_id  TEXT NOT NULL,
  print_id       TEXT NOT NULL,
  quantity       INTEGER NOT NULL CHECK (quantity >= 0),
  updated_at     TEXT NOT NULL,
  PRIMARY KEY (collection_id, print_id),
  FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_collection_cards_print_id
  ON collection_cards(print_id);

CREATE TABLE IF NOT EXISTS collection_consolidations (
  run_id           TEXT PRIMARY KEY,
  collection_id    TEXT NOT NULL,
  consolidated_at  TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
  FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_collection_consolidations_collection_id
  ON collection_consolidations(collection_id);
