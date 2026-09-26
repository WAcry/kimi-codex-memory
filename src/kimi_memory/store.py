"""Durable metadata, fenced generation jobs, and citation receipts (no raw history)."""

import json
import math
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .citations import CitationUse
from .errors import ConfigurationError, LeaseLostError, ModelError
from .files import private_dir
from .kimi import Source

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE summaries (
 source_id TEXT PRIMARY KEY, source_version TEXT NOT NULL, source_updated_at REAL NOT NULL,
 generated_at REAL NOT NULL, cwd TEXT NOT NULL, summary TEXT NOT NULL, slug TEXT NOT NULL,
 usage_count INTEGER, last_usage REAL, selected INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE jobs (
 job_key TEXT PRIMARY KEY, source_version TEXT NOT NULL, success_version TEXT,
 owner TEXT, lease_until REAL NOT NULL DEFAULT 0, retry_after REAL NOT NULL DEFAULT 0,
 attempts_left INTEGER NOT NULL, last_success REAL, error_code TEXT
);
CREATE TABLE citation_receipts (
 event_key TEXT NOT NULL, source_id TEXT NOT NULL, used_at REAL NOT NULL,
 PRIMARY KEY (event_key, source_id)
);
CREATE TABLE scan_state (
 source_id TEXT PRIMARY KEY, updated_at REAL NOT NULL, version TEXT NOT NULL, synced_at REAL NOT NULL
);
CREATE TABLE counters (day TEXT PRIMARY KEY, model_calls INTEGER NOT NULL);
CREATE TABLE publication (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 generation TEXT NOT NULL, owner TEXT NOT NULL, manifest TEXT NOT NULL);
CREATE TABLE runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: Path):
        private_dir(path.parent)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        try:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise ConfigurationError(
                    "Unsupported memory database version; published files remain readable"
                )
            if (
                version == 0
                and self.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
                ).fetchone()
            ):
                raise ConfigurationError("Refusing to initialize an unversioned nonempty database")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            if version == 0:
                self.db.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + SCHEMA
                    + f"PRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;"
                )
            with self.transaction() as db:
                db.execute(
                    "INSERT OR REPLACE INTO runtime_metadata VALUES ('writer_version', ?)",
                    (__version__,),
                )
        except BaseException:
            self.db.close()
            raise

    def close(self) -> None:
        with self.lock:
            self.db.close()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def claim(
        self,
        key: str,
        version: str,
        *,
        now: float,
        lease: int,
        attempts: int,
        cooldown: int = 0,
        repeat: bool = False,
    ) -> str | None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_key=?", (key,)).fetchone()
            if row is not None:
                if row["owner"] and row["lease_until"] > now:
                    return None
                if row["retry_after"] > now:
                    return None
                if row["last_success"] is not None and row["last_success"] + cooldown > now:
                    return None
                if not repeat and row["success_version"] == version:
                    return None
                if not repeat and row["source_version"] == version and row["attempts_left"] <= 0:
                    return None
                remaining = (
                    attempts if row["source_version"] != version or repeat else row["attempts_left"]
                )
            else:
                remaining = attempts
            owner = uuid.uuid4().hex
            db.execute(
                """INSERT INTO jobs(job_key,source_version,owner,lease_until,attempts_left)
                VALUES(?,?,?,?,?) ON CONFLICT(job_key) DO UPDATE SET
                source_version=excluded.source_version,owner=excluded.owner,
                lease_until=excluded.lease_until,attempts_left=excluded.attempts_left,error_code=NULL""",
                (key, version, owner, now + lease, remaining),
            )
            return owner

    def _assert_owner(self, db, key: str, owner: str, now: float) -> None:
        if (
            db.execute(
                "SELECT 1 FROM jobs WHERE job_key=? AND owner=? AND lease_until>?",
                (key, owner, now),
            ).fetchone()
            is None
        ):
            raise LeaseLostError("Generation lease expired or ownership changed")

    def assert_owner(self, key: str, owner: str, now: float | None = None) -> None:
        with self.lock:
            self._assert_owner(self.db, key, owner, time.time() if now is None else now)

    def heartbeat(self, key: str, owner: str, now: float, lease: int) -> None:
        with self.transaction() as db:
            self._assert_owner(db, key, owner, now)
            db.execute(
                "UPDATE jobs SET lease_until=? WHERE job_key=? AND owner=?",
                (now + lease, key, owner),
            )

    def fail(self, key: str, owner: str, *, now: float, delay: int, code: str) -> None:
        with self.transaction() as db:
            db.execute(
                """UPDATE jobs SET owner=NULL,lease_until=0,retry_after=?,
                attempts_left=MAX(0,attempts_left-1),error_code=? WHERE job_key=? AND owner=?""",
                (now + delay, code, key, owner),
            )

    def save_extraction(
        self, source: Source, version: str, summary: str, slug: str, owner: str, now: float
    ) -> None:
        key = "extract:" + source.id
        with self.transaction() as db:
            self._assert_owner(db, key, owner, now)
            if summary:
                db.execute(
                    """INSERT INTO summaries
                    (source_id,source_version,source_updated_at,generated_at,cwd,summary,slug)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
                    source_version=excluded.source_version,source_updated_at=excluded.source_updated_at,
                    generated_at=excluded.generated_at,cwd=excluded.cwd,summary=excluded.summary,slug=excluded.slug""",
                    (source.id, version, source.updated_at, now, source.cwd, summary, slug),
                )
            else:
                db.execute("DELETE FROM summaries WHERE source_id=?", (source.id,))
            db.execute(
                """UPDATE jobs SET owner=NULL,lease_until=0,retry_after=0,
                success_version=?,last_success=?,error_code=NULL WHERE job_key=? AND owner=?""",
                (version, now, key, owner),
            )

    def record_citations(self, uses: list[CitationUse], *, now: float) -> int:
        updated = 0
        with self.transaction() as db:
            for use in uses:
                if not math.isfinite(use.used_at) or use.used_at > now + 300:
                    raise ConfigurationError("Citation completion time is in the future")
                for source_id in sorted(use.source_ids):
                    inserted = db.execute(
                        "INSERT OR IGNORE INTO citation_receipts VALUES(?,?,?)",
                        (use.event_key, source_id, use.used_at),
                    ).rowcount
                    if inserted:
                        updated += db.execute(
                            """UPDATE summaries SET
                            usage_count=COALESCE(usage_count,0)+1,
                            last_usage=MAX(COALESCE(last_usage,?),?) WHERE source_id=?""",
                            (use.used_at, use.used_at, source_id),
                        ).rowcount
        return updated

    def scan_is_current(self, source: Source) -> bool:
        with self.lock:
            row = self.db.execute(
                "SELECT updated_at FROM scan_state WHERE source_id=?", (source.id,)
            ).fetchone()
        return row is not None and row[0] == source.updated_at

    def extraction_due(self, source: Source, now: float) -> bool:
        with self.lock:
            job = self.db.execute(
                "SELECT * FROM jobs WHERE job_key=?", ("extract:" + source.id,)
            ).fetchone()
            scan = self.db.execute(
                "SELECT * FROM scan_state WHERE source_id=?", (source.id,)
            ).fetchone()
        if job is None:
            return True
        if job["owner"] and job["lease_until"] > now or job["retry_after"] > now:
            return False
        if scan and scan["updated_at"] == source.updated_at:
            if job["success_version"] == scan["version"]:
                return False
            if job["source_version"] == scan["version"] and job["attempts_left"] <= 0:
                return False
        return True

    def prepare_extraction_requester(self, revision: str, attempts: int) -> None:
        """New requester code gets one fresh retry budget; successful sources stay put."""
        with self.transaction() as db:
            old = db.execute(
                "SELECT value FROM runtime_metadata WHERE key='extraction_requester'"
            ).fetchone()
            if old is not None and old[0] == revision:
                return
            db.execute(
                """UPDATE jobs SET attempts_left=?,retry_after=0 WHERE job_key LIKE 'extract:%'
                   AND owner IS NULL AND error_code IS NOT NULL
                   AND (success_version IS NULL OR success_version<>source_version)""",
                (attempts,),
            )
            db.execute(
                "INSERT OR REPLACE INTO runtime_metadata VALUES ('extraction_requester',?)",
                (revision,),
            )

    def scanned(self, source: Source, version: str, now: float) -> None:
        with self.transaction() as db:
            db.execute(
                """INSERT INTO scan_state VALUES(?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
                updated_at=excluded.updated_at,version=excluded.version,synced_at=excluded.synced_at""",
                (source.id, source.updated_at, version, now),
            )

    def has_summary(self, source_id: str) -> bool:
        with self.lock:
            return (
                self.db.execute(
                    "SELECT 1 FROM summaries WHERE source_id=?", (source_id,)
                ).fetchone()
                is not None
            )

    def selected(
        self, *, cutoff: float, limit: int, accept=None, preserve: bool = False
    ) -> list[dict]:
        if limit <= 0:
            return []
        with self.lock:
            cursor = self.db.execute(
                """SELECT * FROM summaries
                WHERE COALESCE(last_usage,source_updated_at)>=? OR (? AND selected=1)
                ORDER BY CASE WHEN ? THEN selected ELSE 0 END DESC,
                    COALESCE(usage_count,0) DESC,COALESCE(last_usage,source_updated_at) DESC,
                    source_updated_at DESC,source_id DESC""",
                (cutoff, preserve, preserve),
            )
            rows = []
            for record in cursor:
                row = dict(record)
                if accept is not None and not accept(row):
                    continue
                if len(rows) >= limit and not (preserve and row["selected"]):
                    break
                rows.append(row)
            cursor.close()
        return sorted(rows, key=lambda row: row["source_id"])

    def prune(self, *, cutoff: float, limit: int) -> int:
        with self.transaction() as db:
            return db.execute(
                """DELETE FROM summaries WHERE source_id IN (
                SELECT source_id FROM summaries WHERE selected=0
                AND COALESCE(last_usage,source_updated_at)<?
                ORDER BY COALESCE(last_usage,source_updated_at),source_id LIMIT ?)""",
                (cutoff, limit),
            ).rowcount

    def reserve_model_call(self, *, now: float, daily_limit: int) -> None:
        day = datetime.fromtimestamp(now, UTC).date().isoformat()
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO counters VALUES(?,0)", (day,))
            count = db.execute("SELECT model_calls FROM counters WHERE day=?", (day,)).fetchone()[0]
            if count >= daily_limit:
                raise ModelError("Daily model-call budget reached")
            db.execute("UPDATE counters SET model_calls=model_calls+1 WHERE day=?", (day,))

    def publication_intent(self, generation: str, owner: str, manifest: dict, now: float) -> None:
        with self.transaction() as db:
            self._assert_owner(db, "consolidate", owner, now)
            db.execute(
                "INSERT OR REPLACE INTO publication VALUES(1,?,?,?)",
                (generation, owner, json.dumps(manifest, sort_keys=True)),
            )

    def publish_fenced(self, owner: str, switch) -> None:
        with self.transaction() as db:
            self._assert_owner(db, "consolidate", owner, time.time())
            switch()  # Only an atomic local pointer swap, never model/network work.

    def pending_publication(self) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM publication WHERE singleton=1").fetchone()
        return dict(row) if row else None

    def finalize_publication(self, generation: str, *, now: float) -> None:
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM publication WHERE generation=?", (generation,)
            ).fetchone()
            if row is None:
                return
            manifest = json.loads(row["manifest"])
            db.execute("UPDATE summaries SET selected=0")
            for source in manifest["sources"]:
                db.execute(
                    "UPDATE summaries SET selected=1 WHERE source_id=? AND source_version=?",
                    (source["source_id"], source["source_version"]),
                )
            db.execute(
                """UPDATE jobs SET owner=NULL,lease_until=0,retry_after=0,last_success=?,
                success_version=?,error_code=NULL WHERE job_key='consolidate' AND owner=?""",
                (manifest.get("published_at", now), manifest["input_hash"], row["owner"]),
            )
            db.execute("DELETE FROM publication WHERE singleton=1")

    def abandon_publication(self) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM publication WHERE singleton=1")

    def finish_noop(self, owner: str, version: str, now: float) -> None:
        with self.transaction() as db:
            self._assert_owner(db, "consolidate", owner, now)
            db.execute(
                """UPDATE jobs SET owner=NULL,lease_until=0,retry_after=0,
                success_version=?,last_success=?,error_code=NULL
                WHERE job_key='consolidate' AND owner=?""",
                (version, now, owner),
            )

    def stats(self) -> dict:
        with self.lock:
            return {
                "summaries": self.db.execute("SELECT COUNT(*) FROM summaries").fetchone()[0],
                "citation_receipts": self.db.execute(
                    "SELECT COUNT(*) FROM citation_receipts"
                ).fetchone()[0],
                "running_jobs": self.db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE owner IS NOT NULL"
                ).fetchone()[0],
            }


@contextmanager
def keep_lease(store: Store, key: str, owner: str, *, interval: int, lease: int):
    stop = threading.Event()
    lost: list[BaseException] = []

    def run():
        while not stop.wait(interval):
            try:
                store.heartbeat(key, owner, time.time(), lease)
            except Exception as exc:
                lost.append(exc)
                return

    thread = threading.Thread(target=run, name="memory-lease", daemon=True)
    thread.start()
    try:
        yield
        if lost:
            raise LeaseLostError("Unable to renew generation lease") from lost[0]
        store.assert_owner(key, owner)
    finally:
        stop.set()
        thread.join()
