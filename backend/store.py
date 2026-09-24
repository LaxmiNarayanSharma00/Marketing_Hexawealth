"""File-backed LinkedIn session store (Playwright storage_state)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sessions"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(name: str) -> Path:
    safe = "".join(c for c in name.strip() if c.isalnum() or c in "-_").strip("-_")
    if not safe:
        raise ValueError("invalid session name")
    return DATA_DIR / f"{safe}.json"


def ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def list_sessions() -> list[dict[str, Any]]:
    ensure_dir()
    rows: list[dict[str, Any]] = []
    for path in sorted(DATA_DIR.glob("*.json")):
        rows.append(public_view(json.loads(path.read_text(encoding="utf-8"))))
    return rows


def get_session(name: str) -> dict[str, Any] | None:
    path = _path(name)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def get_session_public(name: str) -> dict[str, Any] | None:
    doc = get_session(name)
    return public_view(doc) if doc else None


def create_session(name: str) -> dict[str, Any]:
    ensure_dir()
    path = _path(name)
    if path.exists():
        raise FileExistsError(f"session '{name}' already exists")
    doc = {
        "name": path.stem,
        "status": "missing",
        "storage_state": {},
        "created_at": _now(),
        "updated_at": _now(),
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return public_view(doc)


def save_storage_state(name: str, storage_state: dict[str, Any]) -> dict[str, Any]:
    ensure_dir()
    path = _path(name)
    if path.exists():
        doc = json.loads(path.read_text(encoding="utf-8"))
    else:
        doc = {"name": path.stem, "created_at": _now()}
    doc["storage_state"] = storage_state
    doc["status"] = "present"
    doc["updated_at"] = _now()
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return public_view(doc)


def set_status(name: str, status: str) -> None:
    doc = get_session(name)
    if not doc:
        return
    doc["status"] = status
    doc["updated_at"] = _now()
    _path(name).write_text(json.dumps(doc, indent=2), encoding="utf-8")


def delete_session(name: str) -> bool:
    path = _path(name)
    if not path.exists():
        return False
    path.unlink()
    return True


def load_storage_state(name: str) -> dict[str, Any]:
    doc = get_session(name)
    if not doc or not (doc.get("storage_state") or {}).get("cookies"):
        raise FileNotFoundError(f"no saved LinkedIn cookies for session '{name}'")
    return doc["storage_state"]


def public_view(doc: dict[str, Any]) -> dict[str, Any]:
    state = doc.get("storage_state") or {}
    cookies = state.get("cookies") or []
    return {
        "name": doc.get("name"),
        "status": doc.get("status", "missing"),
        "has_storage_state": bool(cookies),
        "cookie_count": len(cookies),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }
