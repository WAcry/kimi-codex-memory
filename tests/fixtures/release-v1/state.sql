BEGIN TRANSACTION;
CREATE TABLE citation_receipts (
 event_key TEXT NOT NULL, source_id TEXT NOT NULL, used_at REAL NOT NULL,
 PRIMARY KEY (event_key, source_id)
);
INSERT INTO "citation_receipts" VALUES('fixture-event','session_public_baseline',1700000000.0);
CREATE TABLE counters (day TEXT PRIMARY KEY, model_calls INTEGER NOT NULL);
CREATE TABLE jobs (
 job_key TEXT PRIMARY KEY, source_version TEXT NOT NULL, success_version TEXT,
 owner TEXT, lease_until REAL NOT NULL DEFAULT 0, retry_after REAL NOT NULL DEFAULT 0,
 attempts_left INTEGER NOT NULL, last_success REAL, error_code TEXT
);
INSERT INTO "jobs" VALUES('extract:session_public_baseline','fixture-version','fixture-version',NULL,0.0,0.0,3,1700000000.0,NULL);
CREATE TABLE publication (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 generation TEXT NOT NULL, owner TEXT NOT NULL, manifest TEXT NOT NULL);
CREATE TABLE runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO "runtime_metadata" VALUES('writer_version','1.0.0');
CREATE TABLE scan_state (
 source_id TEXT PRIMARY KEY, updated_at REAL NOT NULL, version TEXT NOT NULL, synced_at REAL NOT NULL
);
INSERT INTO "scan_state" VALUES('session_public_baseline',1699999900.0,'fixture-version',1700000000.0);
CREATE TABLE summaries (
 source_id TEXT PRIMARY KEY, source_version TEXT NOT NULL, source_updated_at REAL NOT NULL,
 generated_at REAL NOT NULL, cwd TEXT NOT NULL, summary TEXT NOT NULL, slug TEXT NOT NULL,
 usage_count INTEGER, last_usage REAL, selected INTEGER NOT NULL DEFAULT 0
);
INSERT INTO "summaries" VALUES('session_public_baseline','fixture-version',1699999900.0,1700000000.0,'/workspace/example','Synthetic release baseline: keep task scope explicit and verify current code before reusing a historical conclusion.','example',1,1700000000.0,1);
COMMIT;
PRAGMA user_version=1;
