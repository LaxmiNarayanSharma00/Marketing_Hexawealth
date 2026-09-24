"""File-backed automation runs."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "automations"

AUTOMATION_KIND_COMPANY_PEOPLE = "company_people_fetch"
AUTOMATION_KIND_BUILD_CONNECTION = "build_connection"
AUTOMATION_KIND_BRAND_ENGAGE = "brand_engage"
KIND_LABELS = {
    AUTOMATION_KIND_COMPANY_PEOPLE: "Company People Fetch",
    AUTOMATION_KIND_BUILD_CONNECTION: "Build Connection",
    AUTOMATION_KIND_BRAND_ENGAGE: "Brand Engage",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _path(run_id: str) -> Path:
    return DATA_DIR / f"{run_id}.json"


def public_view(doc: dict[str, Any]) -> dict[str, Any]:
    kind = doc.get("kind", AUTOMATION_KIND_COMPANY_PEOPLE)
    return {
        "id": doc["id"],
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, kind),
        "session_name": doc.get("session_name", ""),
        "company": doc.get("company", ""),
        "source_id": doc.get("source_id", ""),
        "source_link": doc.get("source_link", ""),
        "max_connections": doc.get("max_connections", 0),
        "max_requests": doc.get("max_requests")
        if doc.get("max_requests") is not None
        else doc.get("max_connections", 0),
        "status": doc.get("status", "pending"),
        "logs": doc.get("logs") or [],
        "error": doc.get("error"),
        "result": doc.get("result") or {},
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def list_runs(*, kind: str | None = None) -> list[dict[str, Any]]:
    ensure_dir()
    rows: list[dict[str, Any]] = []
    for path in sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if kind and doc.get("kind") != kind:
            continue
        rows.append(public_view(doc))
    rows.reverse()
    return rows


def get_run(run_id: str) -> dict[str, Any] | None:
    path = _path(run_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def get_run_public(run_id: str) -> dict[str, Any] | None:
    doc = get_run(run_id)
    return public_view(doc) if doc else None


def create_run(
    *,
    kind: str,
    session_name: str,
    max_connections: int = 0,
    max_requests: int | None = None,
    company: str = "",
    source_id: str = "",
    source_link: str = "",
) -> dict[str, Any]:
    ensure_dir()
    run_id = str(uuid.uuid4())
    req = max_requests if max_requests is not None else max_connections
    doc = {
        "id": run_id,
        "kind": kind,
        "session_name": session_name,
        "company": company,
        "source_id": source_id,
        "source_link": source_link,
        "max_connections": max_connections or req,
        "max_requests": req,
        "status": "pending",
        "logs": [],
        "error": None,
        "result": {},
        "created_at": _now(),
        "updated_at": _now(),
    }
    _path(run_id).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return public_view(doc)


def append_log(run_id: str, msg: str) -> None:
    doc = get_run(run_id)
    if not doc:
        return
    logs = list(doc.get("logs") or [])
    logs.append(msg)
    doc["logs"] = logs
    doc["updated_at"] = _now()
    _path(run_id).write_text(json.dumps(doc, indent=2), encoding="utf-8")


def update_run(run_id: str, **fields: Any) -> dict[str, Any] | None:
    doc = get_run(run_id)
    if not doc:
        return None
    doc.update(fields)
    doc["updated_at"] = _now()
    _path(run_id).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return public_view(doc)
