"""SQLite persistence for Hexawealth Marketing Agents.

Default DB path: <project>/data/hexawealth.db
Override with HEXAWEALTH_DB_PATH (recommended on VPS: /var/lib/hexawealth/app.db).

On first start, existing JSON files under data/ are imported once.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "hexawealth.db"
JSON_ROOT = PROJECT_ROOT / "data"

_lock = threading.RLock()
_initialized = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path() -> Path:
    raw = (os.environ.get("HEXAWEALTH_DB_PATH") or "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_DB_PATH


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'missing',
    storage_state TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    type TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL,
    use_case TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_kind ON sources(source_kind);
CREATE INDEX IF NOT EXISTS idx_sources_link ON sources(link);

CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    session_name TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    source_link TEXT NOT NULL DEFAULT '',
    max_profiles INTEGER NOT NULL DEFAULT 0,
    source_ids TEXT NOT NULL DEFAULT '[]',
    actions TEXT NOT NULL DEFAULT '[]',
    run_time TEXT NOT NULL DEFAULT '09:00',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run_at TEXT,
    last_run_id TEXT,
    last_run_status TEXT,
    last_error TEXT,
    fired_on_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedules_kind ON schedules(kind);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    session_name TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    source_link TEXT NOT NULL DEFAULT '',
    schedule_id TEXT,
    trigger TEXT NOT NULL DEFAULT 'manual',
    max_connections INTEGER NOT NULL DEFAULT 0,
    max_requests INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    result TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_kind_created ON runs(kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);

CREATE TABLE IF NOT EXISTS run_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_run_logs_run ON run_logs(run_id, id);

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    linkedin_url TEXT NOT NULL UNIQUE,
    name TEXT,
    location TEXT,
    about TEXT,
    current_job_title TEXT,
    current_company TEXT,
    open_to_work INTEGER NOT NULL DEFAULT 0,
    experiences TEXT NOT NULL DEFAULT '[]',
    educations TEXT NOT NULL DEFAULT '[]',
    contacts TEXT NOT NULL DEFAULT '[]',
    interests TEXT NOT NULL DEFAULT '[]',
    accomplishments TEXT NOT NULL DEFAULT '[]',
    source_company TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    automation_id TEXT,
    session_name TEXT,
    connection_status TEXT NOT NULL DEFAULT 'none',
    connection_note TEXT NOT NULL DEFAULT '',
    connection_updated_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_profiles_source_id ON profiles(source_id);
CREATE INDEX IF NOT EXISTS idx_profiles_source_company ON profiles(source_company);
CREATE INDEX IF NOT EXISTS idx_profiles_connection ON profiles(connection_status);
CREATE INDEX IF NOT EXISTS idx_profiles_updated ON profiles(updated_at DESC);

CREATE TABLE IF NOT EXISTS engagements (
    session_name TEXT NOT NULL,
    post_urn TEXT NOT NULL,
    post_url TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    liked INTEGER NOT NULL DEFAULT 0,
    commented INTEGER NOT NULL DEFAULT 0,
    reposted INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_name, post_urn)
);
CREATE INDEX IF NOT EXISTS idx_engagements_done ON engagements(session_name, done);
"""


def _dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def _loads(raw: str | None, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def init_db() -> Path:
    """Create schema and import legacy JSON once. Safe to call repeatedly."""
    global _initialized
    with _lock:
        path = db_path()
        with get_db() as conn:
            conn.executescript(SCHEMA_SQL)
            migrated = conn.execute(
                "SELECT value FROM meta WHERE key = ?", ("json_migrated",)
            ).fetchone()
            if not migrated:
                n = _migrate_json_files(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    ("json_migrated", _now()),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    ("json_migrated_count", str(n)),
                )
                if n:
                    logger.info("Migrated %s JSON records into SQLite at %s", n, path)
                else:
                    logger.info("SQLite ready at %s (no JSON to migrate)", path)
            else:
                logger.info("SQLite ready at %s", path)
        _initialized = True
        return path


def ensure_db() -> None:
    if not _initialized:
        init_db()


def _migrate_json_files(conn: sqlite3.Connection) -> int:
    total = 0
    total += _migrate_sessions(conn)
    total += _migrate_sources(conn)
    total += _migrate_schedules(conn)
    total += _migrate_runs(conn)
    total += _migrate_profiles(conn)
    total += _migrate_engagements(conn)
    return total


def _read_json_dir(subdir: str) -> list[dict[str, Any]]:
    folder = JSON_ROOT / subdir
    if not folder.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                rows.append(doc)
        except Exception as exc:
            logger.warning("Skip bad JSON %s: %s", path, exc)
    return rows


def _migrate_sessions(conn: sqlite3.Connection) -> int:
    n = 0
    for doc in _read_json_dir("sessions"):
        name = (doc.get("name") or "").strip()
        if not name:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO sessions(name, status, storage_state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                name,
                doc.get("status") or "missing",
                _dumps(doc.get("storage_state") or {}),
                doc.get("created_at") or _now(),
                doc.get("updated_at") or _now(),
            ),
        )
        n += 1
    return n


def _migrate_sources(conn: sqlite3.Connection) -> int:
    n = 0
    for doc in _read_json_dir("sources"):
        sid = doc.get("id")
        if not sid:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO sources(
                id, source_kind, type, company, link, use_case, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sid,
                doc.get("source_kind") or "company_peoples",
                doc.get("type") or "individual",
                doc.get("company") or "",
                doc.get("link") or "",
                doc.get("use_case") or "",
                doc.get("created_at") or _now(),
                doc.get("updated_at") or _now(),
            ),
        )
        n += 1
    return n


def _migrate_schedules(conn: sqlite3.Connection) -> int:
    n = 0
    for doc in _read_json_dir("schedules"):
        sid = doc.get("id")
        if not sid:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO schedules(
                id, kind, session_name, source_id, company, source_link, max_profiles,
                source_ids, actions, run_time, enabled, last_run_at, last_run_id,
                last_run_status, last_error, fired_on_date, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sid,
                doc.get("kind") or "company_people_fetch",
                doc.get("session_name") or "",
                doc.get("source_id") or "",
                doc.get("company") or "",
                doc.get("source_link") or "",
                int(doc.get("max_profiles") or 0),
                _dumps(doc.get("source_ids") or []),
                _dumps(doc.get("actions") or []),
                doc.get("run_time") or "09:00",
                1 if doc.get("enabled", True) else 0,
                doc.get("last_run_at"),
                doc.get("last_run_id"),
                doc.get("last_run_status"),
                doc.get("last_error"),
                doc.get("fired_on_date"),
                doc.get("created_at") or _now(),
                doc.get("updated_at") or _now(),
            ),
        )
        n += 1
    return n


def _migrate_runs(conn: sqlite3.Connection) -> int:
    n = 0
    for doc in _read_json_dir("automations"):
        rid = doc.get("id")
        if not rid:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO runs(
                id, kind, session_name, company, source_id, source_link, schedule_id,
                trigger, max_connections, max_requests, status, error, result,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                doc.get("kind") or "company_people_fetch",
                doc.get("session_name") or "",
                doc.get("company") or "",
                doc.get("source_id") or "",
                doc.get("source_link") or "",
                doc.get("schedule_id"),
                doc.get("trigger") or "manual",
                int(doc.get("max_connections") or 0),
                int(
                    doc.get("max_requests")
                    if doc.get("max_requests") is not None
                    else doc.get("max_connections")
                    or 0
                ),
                doc.get("status") or "pending",
                doc.get("error"),
                _dumps(doc.get("result") or {}),
                doc.get("created_at") or _now(),
                doc.get("updated_at") or _now(),
            ),
        )
        conn.execute("DELETE FROM run_logs WHERE run_id = ?", (rid,))
        for msg in doc.get("logs") or []:
            conn.execute(
                "INSERT INTO run_logs(run_id, message, created_at) VALUES (?, ?, ?)",
                (rid, str(msg), doc.get("updated_at") or _now()),
            )
        n += 1
    return n


def _migrate_profiles(conn: sqlite3.Connection) -> int:
    n = 0
    for doc in _read_json_dir("profiles"):
        url = (doc.get("linkedin_url") or "").strip()
        if not url:
            continue
        pid = doc.get("id") or url
        conn.execute(
            """
            INSERT OR REPLACE INTO profiles(
                id, linkedin_url, name, location, about, current_job_title,
                current_company, open_to_work, experiences, educations, contacts,
                interests, accomplishments, source_company, source_id, automation_id,
                session_name, connection_status, connection_note, connection_updated_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pid,
                url,
                doc.get("name"),
                doc.get("location"),
                doc.get("about"),
                doc.get("current_job_title"),
                doc.get("current_company"),
                1 if doc.get("open_to_work") else 0,
                _dumps(doc.get("experiences") or []),
                _dumps(doc.get("educations") or []),
                _dumps(doc.get("contacts") or []),
                _dumps(doc.get("interests") or []),
                _dumps(doc.get("accomplishments") or []),
                doc.get("source_company") or "",
                doc.get("source_id") or "",
                doc.get("automation_id"),
                doc.get("session_name"),
                doc.get("connection_status") or "none",
                doc.get("connection_note") or "",
                doc.get("connection_updated_at"),
                doc.get("created_at") or _now(),
                doc.get("updated_at") or _now(),
            ),
        )
        n += 1
    return n


def _migrate_engagements(conn: sqlite3.Connection) -> int:
    n = 0
    for doc in _read_json_dir("engagements"):
        session = (doc.get("session_name") or "").strip()
        urn = (doc.get("post_urn") or "").strip()
        if not session or not urn:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO engagements(
                session_name, post_urn, post_url, source_url, liked, commented,
                reposted, done, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session,
                urn,
                doc.get("post_url") or "",
                doc.get("source_url") or "",
                1 if doc.get("liked") else 0,
                1 if doc.get("commented") else 0,
                1 if doc.get("reposted") else 0,
                1 if doc.get("done") else 0,
                doc.get("note") or "",
                doc.get("created_at") or _now(),
                doc.get("updated_at") or _now(),
            ),
        )
        n += 1
    return n


# Re-export helpers for stores
dumps = _dumps
loads = _loads
now = _now
