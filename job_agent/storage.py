"""
SQLite storage module — thread-safe operations for the seen_jobs table.
"""

import hashlib
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from config import DB_PATH

logger = logging.getLogger(__name__)

# Thread-safety lock for all write operations
_db_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    """Create a new SQLite connection (call per-operation for thread safety)."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the seen_jobs table if it doesn't exist."""
    conn = _connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_jobs (
                id           TEXT PRIMARY KEY,
                url          TEXT,
                title        TEXT,
                company      TEXT,
                location     TEXT,
                country      TEXT,
                salary       TEXT,
                score        INTEGER DEFAULT 0,
                visa_likely  BOOLEAN DEFAULT FALSE,
                reason       TEXT,
                source       TEXT,
                first_seen   TIMESTAMP,
                notified     BOOLEAN DEFAULT FALSE
            )
        """)
        conn.commit()
        logger.info("Database initialised at %s", DB_PATH)
    finally:
        conn.close()


def job_id(url: str) -> str:
    """Generate a deterministic ID from a job URL using MD5."""
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def job_exists(url: str) -> bool:
    """Check if a job URL has already been stored."""
    jid = job_id(url)
    conn = _connect()
    try:
        row = conn.execute("SELECT 1 FROM seen_jobs WHERE id = ?", (jid,)).fetchone()
        return row is not None
    finally:
        conn.close()


def insert_job(
    url: str,
    title: str,
    company: str,
    location: str,
    country: str,
    salary: str,
    source: str,
    score: int = 0,
    visa_likely: bool = False,
    reason: str = "",
) -> bool:
    """
    Insert a job into the database. Returns True if inserted (new),
    False if it already existed (dedup).
    """
    jid = job_id(url)
    now = datetime.now(timezone.utc).isoformat()

    with _db_lock:
        conn = _connect()
        try:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO seen_jobs
                    (id, url, title, company, location, country, salary,
                     score, visa_likely, reason, source, first_seen, notified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (jid, url, title, company, location, country, salary,
                 score, visa_likely, reason, source, now, False),
            )
            conn.commit()
            inserted = cursor.rowcount > 0
            if inserted:
                logger.debug("New job stored: %s — %s", title, url)
            return inserted
        finally:
            conn.close()


def update_score(url: str, score: int, visa_likely: bool, reason: str) -> None:
    """Update the LLM score for an existing job."""
    jid = job_id(url)
    with _db_lock:
        conn = _connect()
        try:
            conn.execute(
                """
                UPDATE seen_jobs
                SET score = ?, visa_likely = ?, reason = ?
                WHERE id = ?
                """,
                (score, visa_likely, reason, jid),
            )
            conn.commit()
        finally:
            conn.close()


def get_unnotified_jobs(min_score: int = 0) -> list[dict]:
    """Return all jobs where notified=FALSE and score >= min_score, ordered by score DESC."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT * FROM seen_jobs
            WHERE notified = FALSE AND score >= ?
            ORDER BY score DESC, country ASC
            """,
            (min_score,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_notified(urls: list[str]) -> None:
    """Mark a list of job URLs as notified=TRUE."""
    if not urls:
        return
    jids = [job_id(u) for u in urls]
    with _db_lock:
        conn = _connect()
        try:
            conn.executemany(
                "UPDATE seen_jobs SET notified = TRUE WHERE id = ?",
                [(jid,) for jid in jids],
            )
            conn.commit()
            logger.info("Marked %d job(s) as notified", len(jids))
        finally:
            conn.close()


def get_stats() -> dict:
    """Return basic database statistics."""
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]
        unnotified = conn.execute(
            "SELECT COUNT(*) FROM seen_jobs WHERE notified = FALSE"
        ).fetchone()[0]
        scored = conn.execute(
            "SELECT COUNT(*) FROM seen_jobs WHERE score > 0"
        ).fetchone()[0]
        return {"total": total, "unnotified": unnotified, "scored": scored}
    finally:
        conn.close()
