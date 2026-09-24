"""SQLite-backed scraped LinkedIn profiles."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from db import dumps, ensure_db, get_db, loads, now


def ensure_dir() -> None:
    ensure_db()


def _key_from_url(url: str) -> str:
    canonical = canonicalize_profile_url(url)
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", canonical.lower()).strip("-")[:80]
    digest = hashlib.sha1(canonical.encode()).hexdigest()[:10]
    return f"{slug}-{digest}"


def canonicalize_profile_url(url: str) -> str:
    """Stable key for dedupe: https://www.linkedin.com/in/{slug} (no trailing slash)."""
    raw = (url or "").strip()
    if raw.startswith("/"):
        raw = "https://www.linkedin.com" + raw
    raw = raw.split("?")[0].split("#")[0].rstrip("/")
    m = re.search(r"(https?://(?:[a-z0-9-]+\.)?linkedin\.com/in/[^/]+)", raw, re.I)
    if m:
        path = re.search(r"/in/[^/]+", m.group(1), re.I)
        if path:
            return f"https://www.linkedin.com{path.group(0).rstrip('/')}"
    return raw.lower()


def _row_to_doc(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "linkedin_url": row["linkedin_url"],
        "name": row["name"],
        "location": row["location"],
        "about": row["about"],
        "current_job_title": row["current_job_title"],
        "current_company": row["current_company"],
        "open_to_work": bool(row["open_to_work"]),
        "experiences": loads(row["experiences"], []),
        "educations": loads(row["educations"], []),
        "contacts": loads(row["contacts"], []),
        "interests": loads(row["interests"], []),
        "accomplishments": loads(row["accomplishments"], []),
        "source_company": row["source_company"] or "",
        "source_id": row["source_id"] or "",
        "automation_id": row["automation_id"],
        "session_name": row["session_name"],
        "connection_status": row["connection_status"] or "none",
        "connection_note": row["connection_note"] or "",
        "connection_updated_at": row["connection_updated_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def profile_exists(url: str) -> bool:
    ensure_db()
    target = canonicalize_profile_url(url)
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM profiles WHERE linkedin_url = ?",
            (target,),
        ).fetchone()
        if row:
            return True
        # Legacy: match by canonicalizing stored URLs that may differ slightly.
        rows = conn.execute("SELECT linkedin_url FROM profiles").fetchall()
    for r in rows:
        if canonicalize_profile_url(r["linkedin_url"] or "") == target:
            return True
    return False


def existing_profile_urls() -> set[str]:
    ensure_db()
    with get_db() as conn:
        rows = conn.execute("SELECT linkedin_url FROM profiles").fetchall()
    urls: set[str] = set()
    for r in rows:
        u = canonicalize_profile_url(r["linkedin_url"] or "")
        if u:
            urls.add(u)
    return urls


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    ensure_db()
    url = profile.get("linkedin_url") or ""
    if not url:
        raise ValueError("linkedin_url required")
    canonical = canonicalize_profile_url(url) or url
    profile = {**profile, "linkedin_url": canonical}
    key = _key_from_url(canonical)
    ts = now()

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM profiles WHERE linkedin_url = ?",
            (canonical,),
        ).fetchone()
        if not row:
            # Try legacy key match
            row = conn.execute(
                "SELECT * FROM profiles WHERE id = ?", (key,)
            ).fetchone()

        if row:
            existing = _row_to_doc(row)
            doc = {**existing, **profile, "updated_at": ts}
            if "created_at" not in doc or not doc["created_at"]:
                doc["created_at"] = existing.get("created_at") or ts
            doc["id"] = existing.get("id") or key
            conn.execute(
                """
                UPDATE profiles SET
                    linkedin_url = ?, name = ?, location = ?, about = ?,
                    current_job_title = ?, current_company = ?, open_to_work = ?,
                    experiences = ?, educations = ?, contacts = ?, interests = ?,
                    accomplishments = ?, source_company = ?, source_id = ?,
                    automation_id = ?, session_name = ?, connection_status = ?,
                    connection_note = ?, connection_updated_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    doc["linkedin_url"],
                    doc.get("name"),
                    doc.get("location"),
                    doc.get("about"),
                    doc.get("current_job_title"),
                    doc.get("current_company"),
                    1 if doc.get("open_to_work") else 0,
                    dumps(doc.get("experiences") or []),
                    dumps(doc.get("educations") or []),
                    dumps(doc.get("contacts") or []),
                    dumps(doc.get("interests") or []),
                    dumps(doc.get("accomplishments") or []),
                    doc.get("source_company") or "",
                    doc.get("source_id") or "",
                    doc.get("automation_id"),
                    doc.get("session_name"),
                    doc.get("connection_status") or "none",
                    doc.get("connection_note") or "",
                    doc.get("connection_updated_at"),
                    ts,
                    doc["id"],
                ),
            )
        else:
            doc = {**profile, "id": key, "created_at": ts, "updated_at": ts}
            conn.execute(
                """
                INSERT INTO profiles(
                    id, linkedin_url, name, location, about, current_job_title,
                    current_company, open_to_work, experiences, educations, contacts,
                    interests, accomplishments, source_company, source_id,
                    automation_id, session_name, connection_status, connection_note,
                    connection_updated_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    canonical,
                    doc.get("name"),
                    doc.get("location"),
                    doc.get("about"),
                    doc.get("current_job_title"),
                    doc.get("current_company"),
                    1 if doc.get("open_to_work") else 0,
                    dumps(doc.get("experiences") or []),
                    dumps(doc.get("educations") or []),
                    dumps(doc.get("contacts") or []),
                    dumps(doc.get("interests") or []),
                    dumps(doc.get("accomplishments") or []),
                    doc.get("source_company") or "",
                    doc.get("source_id") or "",
                    doc.get("automation_id"),
                    doc.get("session_name"),
                    doc.get("connection_status") or "none",
                    doc.get("connection_note") or "",
                    doc.get("connection_updated_at"),
                    ts,
                    ts,
                ),
            )
    return public_view(doc)


def public_view(doc: dict[str, Any]) -> dict[str, Any]:
    audience = doc.get("source_company") or ""
    return {
        "id": doc.get("id"),
        "linkedin_url": doc.get("linkedin_url"),
        "name": doc.get("name"),
        "location": doc.get("location"),
        "about": doc.get("about"),
        "current_job_title": doc.get("current_job_title"),
        "current_company": doc.get("current_company"),
        "open_to_work": doc.get("open_to_work", False),
        "experiences": doc.get("experiences") or [],
        "educations": doc.get("educations") or [],
        "contacts": doc.get("contacts") or [],
        "interests": doc.get("interests") or [],
        "accomplishments": doc.get("accomplishments") or [],
        "audience": audience,
        "source_company": audience,
        "source_id": doc.get("source_id") or "",
        "automation_id": doc.get("automation_id"),
        "session_name": doc.get("session_name"),
        "connection_status": doc.get("connection_status") or "none",
        "connection_note": doc.get("connection_note") or "",
        "connection_updated_at": doc.get("connection_updated_at"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def _matches_audience(
    doc: dict[str, Any],
    *,
    source_id: str | None = None,
    source_company: str | None = None,
) -> bool:
    if not source_id and not source_company:
        return True
    doc_sid = (doc.get("source_id") or "").strip()
    doc_company = (doc.get("source_company") or "").strip()
    if source_id and doc_sid:
        return doc_sid == source_id
    if source_id and source_company:
        return doc_company.lower() == source_company.lower()
    if source_id:
        return False
    if source_company:
        return doc_company.lower() == source_company.lower()
    return True


def list_profiles(
    *,
    source_company: str | None = None,
    source_id: str | None = None,
    automation_id: str | None = None,
) -> list[dict[str, Any]]:
    ensure_db()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM profiles ORDER BY updated_at DESC"
        ).fetchall()
        docs = [_row_to_doc(r) for r in rows]
    out: list[dict[str, Any]] = []
    for doc in docs:
        if source_id and not _matches_audience(
            doc, source_id=source_id, source_company=source_company
        ):
            continue
        if (
            not source_id
            and source_company
            and (doc.get("source_company") or "").lower() != source_company.lower()
        ):
            continue
        if automation_id and doc.get("automation_id") != automation_id:
            continue
        out.append(public_view(doc))
    return out


def list_profiles_for_connect(
    *,
    limit: int = 10,
    source_id: str | None = None,
    source_company: str | None = None,
) -> list[dict[str, Any]]:
    """Profiles that have not yet been sent a connection request."""
    ensure_db()
    skip = {"pending", "connected", "sent", "self"}
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM profiles ORDER BY updated_at ASC"
        ).fetchall()
        docs = [_row_to_doc(r) for r in rows]
    out: list[dict[str, Any]] = []
    for doc in docs:
        status = (doc.get("connection_status") or "none").lower()
        if status in skip:
            continue
        if not (doc.get("linkedin_url") or "").strip():
            continue
        if not _matches_audience(
            doc, source_id=source_id, source_company=source_company
        ):
            continue
        out.append(public_view(doc))
        if len(out) >= limit:
            break
    return out


def count_eligible_for_connect(
    *,
    source_id: str | None = None,
    source_company: str | None = None,
) -> int:
    return len(
        list_profiles_for_connect(
            limit=10_000,
            source_id=source_id,
            source_company=source_company,
        )
    )


def list_audiences() -> list[dict[str, Any]]:
    """Distinct fetch audiences from stored profiles (for Build Connection UI)."""
    ensure_db()
    buckets: dict[str, dict[str, Any]] = {}
    skip = {"pending", "connected", "sent", "self"}
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM profiles").fetchall()
        docs = [_row_to_doc(r) for r in rows]
    for doc in docs:
        company = (doc.get("source_company") or "").strip()
        sid = (doc.get("source_id") or "").strip()
        if not company and not sid:
            continue
        key = sid or f"name:{company.lower()}"
        bucket = buckets.setdefault(
            key,
            {
                "source_id": sid,
                "company": company,
                "audience": company,
                "total": 0,
                "eligible": 0,
            },
        )
        if company and not bucket["company"]:
            bucket["company"] = company
            bucket["audience"] = company
        if sid and not bucket["source_id"]:
            bucket["source_id"] = sid
        bucket["total"] += 1
        status = (doc.get("connection_status") or "none").lower()
        if status not in skip and (doc.get("linkedin_url") or "").strip():
            bucket["eligible"] += 1

    rows_out = list(buckets.values())
    rows_out.sort(key=lambda r: (r.get("company") or "").lower())
    return rows_out


def update_connection_status(
    url: str, status: str, *, note: str = ""
) -> dict[str, Any] | None:
    ensure_db()
    canonical = canonicalize_profile_url(url)
    ts = now()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM profiles WHERE linkedin_url = ?",
            (canonical,),
        ).fetchone()
        if not row:
            for candidate in conn.execute("SELECT * FROM profiles").fetchall():
                if canonicalize_profile_url(candidate["linkedin_url"] or "") == canonical:
                    row = candidate
                    break
        if not row:
            return None
        conn.execute(
            """
            UPDATE profiles
            SET connection_status = ?, connection_note = ?,
                connection_updated_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, note, ts, ts, row["id"]),
        )
        row = conn.execute(
            "SELECT * FROM profiles WHERE id = ?", (row["id"],)
        ).fetchone()
        return public_view(_row_to_doc(row))


def backfill_source_ids(by_company: dict[str, str]) -> int:
    """Attach source_id to profiles that only have source_company."""
    ensure_db()
    updated = 0
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, source_company FROM profiles
            WHERE source_id IS NULL OR TRIM(source_id) = ''
            """
        ).fetchall()
        for row in rows:
            company = (row["source_company"] or "").strip().lower()
            sid = by_company.get(company)
            if not sid:
                continue
            conn.execute(
                "UPDATE profiles SET source_id = ?, updated_at = ? WHERE id = ?",
                (sid, now(), row["id"]),
            )
            updated += 1
    return updated
