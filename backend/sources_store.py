"""File-backed sources store.

Phase 2 source kinds:
  1. Company Peoples — LinkedIn company /people/ URLs
  2. Influencer — LinkedIn profile URLs
  3. Individual — LinkedIn profile URLs (reach out)
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, unquote

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sources"

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _path(source_id: str) -> Path:
    return DATA_DIR / f"{source_id}.json"


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
    # Fallback: last meaningful path segment
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
    ensure_dir()
    rows: list[dict[str, Any]] = []
    for path in sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if source_kind and doc.get("source_kind") != source_kind:
            continue
        rows.append(public_view(doc))
    rows.reverse()
    return rows


def get_source(source_id: str) -> dict[str, Any] | None:
    path = _path(source_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_unique_link(normalized: str, *, source_kind: str) -> None:
    for existing in list_sources(source_kind=source_kind):
        if existing["link"].rstrip("/").lower() == normalized.rstrip("/").lower():
            raise FileExistsError(f"source already exists for {normalized}")


def create_company_peoples_source(
    *,
    link: str,
    company: str = "",
    type_: str = TYPE_INDIVIDUAL,
    use_case: str = USE_CASE_INCREASE_NETWORK,
) -> dict[str, Any]:
    ensure_dir()
    normalized = normalize_company_people_url(link)
    company_name = (company or "").strip() or company_from_people_url(normalized)
    if not company_name:
        raise ValueError("company is required")
    _assert_unique_link(normalized, source_kind=SOURCE_KIND_COMPANY_PEOPLES)

    source_id = str(uuid.uuid4())
    doc = {
        "id": source_id,
        "source_kind": SOURCE_KIND_COMPANY_PEOPLES,
        "type": (type_ or TYPE_INDIVIDUAL).strip().lower() or TYPE_INDIVIDUAL,
        "company": company_name,
        "link": normalized,
        "use_case": (use_case or USE_CASE_INCREASE_NETWORK).strip().lower()
        or USE_CASE_INCREASE_NETWORK,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _path(source_id).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return public_view(doc)


def create_influencer_source(
    *,
    link: str,
    company: str = "",
    type_: str = TYPE_INFLUENCER,
    use_case: str = USE_CASE_INCREASE_VISIBILITY,
) -> dict[str, Any]:
    """Type 2 · Influencer. `company` stores the influencer's display name."""
    ensure_dir()
    normalized = normalize_profile_url(link)
    name = (company or "").strip() or name_from_profile_url(normalized)
    if not name:
        raise ValueError("name is required")
    _assert_unique_link(normalized, source_kind=SOURCE_KIND_INFLUENCER)

    source_id = str(uuid.uuid4())
    doc = {
        "id": source_id,
        "source_kind": SOURCE_KIND_INFLUENCER,
        "type": (type_ or TYPE_INFLUENCER).strip().lower() or TYPE_INFLUENCER,
        "company": name,
        "link": normalized,
        "use_case": (use_case or USE_CASE_INCREASE_VISIBILITY).strip().lower()
        or USE_CASE_INCREASE_VISIBILITY,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _path(source_id).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return public_view(doc)


def create_individual_source(
    *,
    link: str,
    company: str = "",
    type_: str = TYPE_INDIVIDUAL,
    use_case: str = USE_CASE_REACH_OUT,
) -> dict[str, Any]:
    """Type 3 · Individual. `company` stores the person's display name."""
    ensure_dir()
    normalized = normalize_profile_url(link)
    name = (company or "").strip() or name_from_profile_url(normalized)
    if not name:
        raise ValueError("name is required")
    _assert_unique_link(normalized, source_kind=SOURCE_KIND_INDIVIDUAL)

    source_id = str(uuid.uuid4())
    doc = {
        "id": source_id,
        "source_kind": SOURCE_KIND_INDIVIDUAL,
        "type": (type_ or TYPE_INDIVIDUAL).strip().lower() or TYPE_INDIVIDUAL,
        "company": name,
        "link": normalized,
        "use_case": (use_case or USE_CASE_REACH_OUT).strip().lower()
        or USE_CASE_REACH_OUT,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _path(source_id).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return public_view(doc)


def delete_source(source_id: str) -> bool:
    path = _path(source_id)
    if not path.exists():
        return False
    path.unlink()
    return True
