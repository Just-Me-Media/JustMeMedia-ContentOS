-- NOTE: This schema file is legacy / documentation-only. The live schema is
-- defined in app/server.py::connect_db() and creates these tables:
--   drafts, content_items, content_versions, sources, claims, approvals,
--   rejected_sources, github_repos, draft_versions, activity_log, templates,
--   github_top10_issues
-- Do not use this file for migrations; it is preserved for reference only.
-- Initial logical schema. Apply through a migration runner in a later implementation.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS content_items (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  pillar TEXT,
  status TEXT NOT NULL DEFAULT 'IDEA',
  audience TEXT,
  objective TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  current_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS content_versions (
  id TEXT PRIMARY KEY,
  content_id TEXT NOT NULL REFERENCES content_items(id),
  version INTEGER NOT NULL,
  platform TEXT,
  body TEXT NOT NULL,
  visual_brief TEXT,
  created_at TEXT NOT NULL,
  created_by TEXT,
  UNIQUE(content_id, version, platform)
);

CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  title TEXT,
  publisher TEXT,
  published_at TEXT,
  retrieved_at TEXT NOT NULL,
  source_type TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS claims (
  id TEXT PRIMARY KEY,
  content_version_id TEXT NOT NULL REFERENCES content_versions(id),
  claim_text TEXT NOT NULL,
  verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED',
  notes TEXT
);

CREATE TABLE IF NOT EXISTS claim_sources (
  claim_id TEXT NOT NULL REFERENCES claims(id),
  source_id TEXT NOT NULL REFERENCES sources(id),
  support_note TEXT,
  PRIMARY KEY(claim_id, source_id)
);

CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  content_version_id TEXT NOT NULL REFERENCES content_versions(id),
  action TEXT NOT NULL,
  decision TEXT NOT NULL,
  approved_at TEXT,
  approved_by TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS provider_runs (
  id TEXT PRIMARY KEY,
  task_id TEXT,
  provider_id TEXT NOT NULL,
  model_id TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  latency_ms INTEGER,
  usage_json TEXT,
  error_summary TEXT
);

CREATE TABLE IF NOT EXISTS analytics_snapshots (
  id TEXT PRIMARY KEY,
  content_version_id TEXT NOT NULL REFERENCES content_versions(id),
  platform TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  metrics_json TEXT NOT NULL
);
