"""SQLite-backed sources store.

Phase 2 source kinds:
  1. Company Peoples — LinkedIn company /people/ URLs
  2. Influencer — LinkedIn profile URLs
  3. Individual — LinkedIn profile URLs (reach out)
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import urlparse, unquote

from db import ensure_db, get_db, now

SOURCE_KIND_COMPANY_PEOPLES = "company_peoples"
SOURCE_KIND_INFLUENCER = "influencer"
SOURCE_KIND_INDIVIDUAL = "individual"

TYPE_INDIVIDUAL = "individual"
TYPE_INFLUENCER = "influencer"

USE_CASE_INCREASE_NETWORK = "increase_network"
USE_CASE_INCREASE_VISIBILITY = "increase_visibility"
USE_CASE_REACH_OUT = "reach_out"

KIND_LABELS = {
    SOURCE_KIND_COMPANY_PEOPLES: "Company Peoples",
    SOURCE_KIND_INFLUENCER: "Influencer",
    SOURCE_KIND_INDIVIDUAL: "Individual",
}

_COMPANY_PEOPLE_RE = re.compile(
    r"^https?://([a-z0-9-]+\.)?linkedin\.com/company/([^/?#]+)/people/?$",
    re.IGNORECASE,
)
_SCHOOL_ALUMNI_RE = re.compile(
    r"^https?://([a-z0-9-]+\.)?linkedin\.com/school/([^/?#]+)/alumni/?$",
    re.IGNORECASE,
)


def ensure_dir() -> None:
    ensure_db()


def _slug_to_title(slug: str) -> str:
    return unquote(slug).replace("-", " ").title()


def normalize_company_people_url(url: str) -> str:
    """Accept any LinkedIn URL (company/people, school/alumni, etc.)."""
    raw = (url or "").strip()
    if not raw:
        raise ValueError("link is required")
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if "linkedin.com" not in host:
        raise ValueError("link must be a LinkedIn URL")
    path = (parsed.path or "").rstrip("/")
    path = f"{path}/" if path else "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"https://www.linkedin.com{path}{query}"


def normalize_profile_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("link is required")
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if "linkedin.com" not in host:
        raise ValueError("link must be a LinkedIn URL")
    path = (parsed.path or "").rstrip("/")
    m = re.match(r"^/in/([^/]+)$", path, re.IGNORECASE)
    if not m:
        raise ValueError(
            "link must look like https://www.linkedin.com/in/{username}/"
        )
    slug = unquote(m.group(1))
    return f"https://www.linkedin.com/in/{slug}/"


def company_from_people_url(url: str) -> str:
    raw = (url or "").strip()
    m = _COMPANY_PEOPLE_RE.match(raw)
    if m:
        return _slug_to_title(m.group(2))
    m = _SCHOOL_ALUMNI_RE.match(raw)
    if m:
        return _slug_to_title(m.group(2))
    try:
        parts = [p for p in urlparse(raw).path.split("/") if p]
        skip = {"company", "school", "people", "alumni", "in", "www"}
        for part in reversed(parts):
            if part.lower() not in skip:
                return _slug_to_title(part)
    except Exception:
        pass
    return ""


def name_from_profile_url(url: str) -> str:
    try:
        path = urlparse(url).path.rstrip("/")
        slug = path.split("/")[-1]
        return unquote(slug).replace("-", " ").title()
    except Exception:
        return ""


def _row_to_doc(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_kind": row["source_kind"],
        "type": row["type"],
        "company": row["company"] or "",
        "link": row["link"] or "",
        "use_case": row["use_case"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def public_view(doc: dict[str, Any]) -> dict[str, Any]:
    kind = doc.get("source_kind", SOURCE_KIND_COMPANY_PEOPLES)
    return {
        "id": doc["id"],
        "source_kind": kind,
        "source_kind_label": KIND_LABELS.get(kind, kind),
        "type": doc.get("type", TYPE_INDIVIDUAL),
        "company": doc.get("company", ""),
        "link": doc.get("link", ""),
        "use_case": doc.get("use_case", USE_CASE_INCREASE_NETWORK),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def list_sources(*, source_kind: str | None = None) -> list[dict[str, Any]]:
    ensure_db()
    with get_db() as conn:
        if source_kind:
            rows = conn.execute(
                "SELECT * FROM sources WHERE source_kind = ? ORDER BY created_at DESC",
                (source_kind,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sources ORDER BY created_at DESC"
            ).fetchall()
    return [public_view(_row_to_doc(r)) for r in rows]


def get_source(source_id: str) -> dict[str, Any] | None:
    ensure_db()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
    return _row_to_doc(row) if row else None


def _assert_unique_link(normalized: str, *, source_kind: str) -> None:
    ensure_db()
    target = normalized.rstrip("/").lower()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT link FROM sources WHERE source_kind = ?",
            (source_kind,),
        ).fetchall()
    for row in rows:
        if (row["link"] or "").rstrip("/").lower() == target:
            raise FileExistsError(f"source already exists for {normalized}")


def _insert_source(doc: dict[str, Any]) -> dict[str, Any]:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO sources(
                id, source_kind, type, company, link, use_case, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc["id"],
                doc["source_kind"],
                doc["type"],
                doc["company"],
                doc["link"],
                doc["use_case"],
                doc["created_at"],
                doc["updated_at"],
            ),
        )
    return public_view(doc)


def create_company_peoples_source(
    *,
    link: str,
    company: str = "",
    type_: str = TYPE_INDIVIDUAL,
    use_case: str = USE_CASE_INCREASE_NETWORK,
) -> dict[str, Any]:
    ensure_db()
    normalized = normalize_company_people_url(link)
    company_name = (company or "").strip() or company_from_people_url(normalized)
    if not company_name:
        raise ValueError("company is required")
    _assert_unique_link(normalized, source_kind=SOURCE_KIND_COMPANY_PEOPLES)

    ts = now()
    doc = {
        "id": str(uuid.uuid4()),
        "source_kind": SOURCE_KIND_COMPANY_PEOPLES,
        "type": (type_ or TYPE_INDIVIDUAL).strip().lower() or TYPE_INDIVIDUAL,
        "company": company_name,
        "link": normalized,
        "use_case": (use_case or USE_CASE_INCREASE_NETWORK).strip().lower()
        or USE_CASE_INCREASE_NETWORK,
        "created_at": ts,
        "updated_at": ts,
    }
    return _insert_source(doc)


def create_influencer_source(
    *,
    link: str,
    company: str = "",
    type_: str = TYPE_INFLUENCER,
    use_case: str = USE_CASE_INCREASE_VISIBILITY,
) -> dict[str, Any]:
    """Type 2 · Influencer. `company` stores the influencer's display name."""
    ensure_db()
    normalized = normalize_profile_url(link)
    name = (company or "").strip() or name_from_profile_url(normalized)
    if not name:
        raise ValueError("name is required")
    _assert_unique_link(normalized, source_kind=SOURCE_KIND_INFLUENCER)

    ts = now()
    doc = {
        "id": str(uuid.uuid4()),
        "source_kind": SOURCE_KIND_INFLUENCER,
        "type": (type_ or TYPE_INFLUENCER).strip().lower() or TYPE_INFLUENCER,
        "company": name,
        "link": normalized,
        "use_case": (use_case or USE_CASE_INCREASE_VISIBILITY).strip().lower()
        or USE_CASE_INCREASE_VISIBILITY,
        "created_at": ts,
        "updated_at": ts,
    }
    return _insert_source(doc)


def create_individual_source(
    *,
    link: str,
    company: str = "",
    type_: str = TYPE_INDIVIDUAL,
    use_case: str = USE_CASE_REACH_OUT,
) -> dict[str, Any]:
    """Type 3 · Individual. `company` stores the person's display name."""
    ensure_db()
    normalized = normalize_profile_url(link)
    name = (company or "").strip() or name_from_profile_url(normalized)
    if not name:
        raise ValueError("name is required")
    _assert_unique_link(normalized, source_kind=SOURCE_KIND_INDIVIDUAL)

    ts = now()
    doc = {
        "id": str(uuid.uuid4()),
        "source_kind": SOURCE_KIND_INDIVIDUAL,
        "type": (type_ or TYPE_INDIVIDUAL).strip().lower() or TYPE_INDIVIDUAL,
        "company": name,
        "link": normalized,
        "use_case": (use_case or USE_CASE_REACH_OUT).strip().lower()
        or USE_CASE_REACH_OUT,
        "created_at": ts,
        "updated_at": ts,
    }
    return _insert_source(doc)


def delete_source(source_id: str) -> bool:
    ensure_db()
    with get_db() as conn:
        cur = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        return cur.rowcount > 0
