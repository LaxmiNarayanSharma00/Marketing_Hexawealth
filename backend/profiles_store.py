"""File-backed scraped LinkedIn profiles."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "profiles"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


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


def profile_exists(url: str) -> bool:
    ensure_dir()
    path = DATA_DIR / f"{_key_from_url(url)}.json"
    if path.exists():
        return True
    # Also match older files that may have used a slightly different key.
    target = canonicalize_profile_url(url)
    for p in DATA_DIR.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if canonicalize_profile_url(doc.get("linkedin_url") or "") == target:
                return True
        except Exception:
            continue
    return False


def existing_profile_urls() -> set[str]:
    ensure_dir()
    urls: set[str] = set()
    for path in DATA_DIR.glob("*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            u = canonicalize_profile_url(doc.get("linkedin_url") or "")
            if u:
                urls.add(u)
        except Exception:
            continue
    return urls


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    ensure_dir()
    url = profile.get("linkedin_url") or ""
    if not url:
        raise ValueError("linkedin_url required")
    profile = {**profile, "linkedin_url": canonicalize_profile_url(url) or url}
    key = _key_from_url(profile["linkedin_url"])
    path = DATA_DIR / f"{key}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        doc = {**existing, **profile, "updated_at": _now()}
        if "created_at" not in doc:
            doc["created_at"] = _now()
    else:
        doc = {**profile, "id": key, "created_at": _now(), "updated_at": _now()}
    path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
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
        # Audience = Company Peoples source that fetched this profile.
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


def list_profiles(
    *,
    source_company: str | None = None,
    source_id: str | None = None,
    automation_id: str | None = None,
) -> list[dict[str, Any]]:
    ensure_dir()
    rows: list[dict[str, Any]] = []
    for path in sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        doc = json.loads(path.read_text(encoding="utf-8"))
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
        rows.append(public_view(doc))
    rows.reverse()
    return rows


def _matches_audience(
    doc: dict[str, Any],
    *,
    source_id: str | None = None,
    source_company: str | None = None,
) -> bool:
    """Match by source_id when present; fall back to source_company for older profiles."""
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


def list_profiles_for_connect(
    *,
    limit: int = 10,
    source_id: str | None = None,
    source_company: str | None = None,
) -> list[dict[str, Any]]:
    """Profiles that have not yet been sent a connection request.

    When source_id / source_company is set, only that audience (fetched from that
    Company Peoples source) is considered.
    """
    ensure_dir()
    skip = {"pending", "connected", "sent", "self"}
    rows: list[dict[str, Any]] = []
    for path in sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        doc = json.loads(path.read_text(encoding="utf-8"))
        status = (doc.get("connection_status") or "none").lower()
        if status in skip:
            continue
        if not (doc.get("linkedin_url") or "").strip():
            continue
        if not _matches_audience(
            doc, source_id=source_id, source_company=source_company
        ):
            continue
        rows.append(public_view(doc))
        if len(rows) >= limit:
            break
    return rows


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
    ensure_dir()
    # key -> {source_id, company, total, eligible}
    buckets: dict[str, dict[str, Any]] = {}
    skip = {"pending", "connected", "sent", "self"}
    for path in DATA_DIR.glob("*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
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

    rows = list(buckets.values())
    rows.sort(key=lambda r: (r.get("company") or "").lower())
    return rows


def update_connection_status(
    url: str, status: str, *, note: str = ""
) -> dict[str, Any] | None:
    ensure_dir()
    canonical = canonicalize_profile_url(url)
    path = DATA_DIR / f"{_key_from_url(canonical)}.json"
    doc = None
    if path.exists():
        doc = json.loads(path.read_text(encoding="utf-8"))
    else:
        for p in DATA_DIR.glob("*.json"):
            try:
                candidate = json.loads(p.read_text(encoding="utf-8"))
                if canonicalize_profile_url(candidate.get("linkedin_url") or "") == canonical:
                    path = p
                    doc = candidate
                    break
            except Exception:
                continue
    if not doc:
        return None
    doc["connection_status"] = status
    doc["connection_note"] = note
    doc["connection_updated_at"] = _now()
    doc["updated_at"] = _now()
    path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    return public_view(doc)
