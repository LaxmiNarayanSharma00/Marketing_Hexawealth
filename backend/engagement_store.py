"""Idempotent record of posts already liked/commented/reposted per session."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "engagements"

_ACTIVITY_URN_RE = re.compile(
    r"(urn:li:(?:activity|ugcPost|share):\d+)", re.I
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def canonicalize_post_urn(urn_or_url: str) -> str:
    raw = (urn_or_url or "").strip()
    # SDUI company cards have no activity URN. Keep the componentkey case
    # so the later [componentkey="..."] lookup stays exact.
    if raw.lower().startswith("sdui:"):
        return "sdui:" + raw.split(":", 1)[1]
    m = _ACTIVITY_URN_RE.search(raw)
    if m:
        return m.group(1).lower()
    # Fallback stable key from URL path
    cleaned = raw.split("?")[0].split("#")[0].rstrip("/").lower()
    return cleaned


def _key(session_name: str, post_urn: str) -> str:
    sess = re.sub(r"[^a-zA-Z0-9_-]+", "-", (session_name or "").strip())[:40]
    urn = canonicalize_post_urn(post_urn)
    digest = hashlib.sha1(f"{sess}|{urn}".encode()).hexdigest()[:12]
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", urn)[:60].strip("-")
    return f"{sess}__{slug}__{digest}"


def has_engaged(session_name: str, post_urn: str) -> bool:
    ensure_dir()
    path = DATA_DIR / f"{_key(session_name, post_urn)}.json"
    if not path.exists():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(doc.get("done"))


def mark_engaged(
    *,
    session_name: str,
    post_urn: str,
    post_url: str = "",
    source_url: str = "",
    liked: bool = False,
    commented: bool = False,
    reposted: bool = False,
    note: str = "",
) -> dict[str, Any]:
    ensure_dir()
    urn = canonicalize_post_urn(post_urn)
    path = DATA_DIR / f"{_key(session_name, urn)}.json"
    done = bool(liked and commented and reposted)
    doc = {
        "session_name": session_name,
        "post_urn": urn,
        "post_url": post_url,
        "source_url": source_url,
        "liked": liked,
        "commented": commented,
        "reposted": reposted,
        "done": done,
        "note": note,
        "updated_at": _now(),
    }
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            doc["created_at"] = prev.get("created_at") or _now()
            # Preserve prior success flags
            doc["liked"] = bool(prev.get("liked") or liked)
            doc["commented"] = bool(prev.get("commented") or commented)
            doc["reposted"] = bool(prev.get("reposted") or reposted)
            doc["done"] = bool(doc["liked"] and doc["commented"] and doc["reposted"])
        except Exception:
            doc["created_at"] = _now()
    else:
        doc["created_at"] = _now()
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def get_engagement(session_name: str, post_urn: str) -> dict[str, Any] | None:
    ensure_dir()
    path = DATA_DIR / f"{_key(session_name, post_urn)}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
