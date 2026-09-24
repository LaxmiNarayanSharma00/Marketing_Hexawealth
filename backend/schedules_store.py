"""File-backed automation schedule mappings.

Each schedule maps a logged-in session → a source for a given automation kind,
with a daily local run time, profile/count limit, and pause/start state.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "schedules"

KIND_COMPANY_PEOPLE = "company_people_fetch"
KIND_BUILD_CONNECTION = "build_connection"

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _path(schedule_id: str) -> Path:
    return DATA_DIR / f"{schedule_id}.json"


def normalize_run_time(value: str) -> str:
    raw = (value or "").strip()
    # Browsers may send HH:MM:SS from <input type="time">.
    if len(raw) >= 8 and raw[2] == ":" and raw[5] == ":":
        raw = raw[:5]
    if not _TIME_RE.match(raw):
        raise ValueError("run_time must be HH:MM in 24-hour local time")
    return raw


def public_view(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc["id"],
        "kind": doc.get("kind", KIND_COMPANY_PEOPLE),
        "session_name": doc.get("session_name", ""),
        "source_id": doc.get("source_id", ""),
        "company": doc.get("company", ""),
        "source_link": doc.get("source_link", ""),
        "max_profiles": int(doc.get("max_profiles") or 0),
        "run_time": doc.get("run_time", "09:00"),
        "enabled": bool(doc.get("enabled", True)),
        "last_run_at": doc.get("last_run_at"),
        "last_run_id": doc.get("last_run_id"),
        "last_run_status": doc.get("last_run_status"),
        "last_error": doc.get("last_error"),
        "fired_on_date": doc.get("fired_on_date"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def list_schedules(*, kind: str | None = None) -> list[dict[str, Any]]:
    ensure_dir()
    rows: list[dict[str, Any]] = []
    for path in sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if kind and doc.get("kind") != kind:
            continue
        rows.append(public_view(doc))
    rows.reverse()
    return rows


def get_schedule(schedule_id: str) -> dict[str, Any] | None:
    path = _path(schedule_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def get_schedule_public(schedule_id: str) -> dict[str, Any] | None:
    doc = get_schedule(schedule_id)
    return public_view(doc) if doc else None


def create_schedule(
    *,
    kind: str,
    session_name: str,
    source_id: str,
    company: str = "",
    source_link: str = "",
    max_profiles: int = 10,
    run_time: str = "09:00",
    enabled: bool = True,
) -> dict[str, Any]:
    ensure_dir()
    if max_profiles < 1 or max_profiles > 100:
        raise ValueError("max_profiles must be between 1 and 100")
    run_time = normalize_run_time(run_time)
    schedule_id = str(uuid.uuid4())
    doc = {
        "id": schedule_id,
        "kind": kind,
        "session_name": session_name,
        "source_id": source_id,
        "company": company,
        "source_link": source_link,
        "max_profiles": max_profiles,
        "run_time": run_time,
        "enabled": enabled,
        "last_run_at": None,
        "last_run_id": None,
        "last_run_status": None,
        "last_error": None,
        "fired_on_date": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _path(schedule_id).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return public_view(doc)


def update_schedule(schedule_id: str, **fields: Any) -> dict[str, Any] | None:
    doc = get_schedule(schedule_id)
    if not doc:
        return None
    if "run_time" in fields and fields["run_time"] is not None:
        fields["run_time"] = normalize_run_time(str(fields["run_time"]))
    if "max_profiles" in fields and fields["max_profiles"] is not None:
        n = int(fields["max_profiles"])
        if n < 1 or n > 100:
            raise ValueError("max_profiles must be between 1 and 100")
        fields["max_profiles"] = n
    doc.update(fields)
    doc["updated_at"] = _now()
    _path(schedule_id).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return public_view(doc)


def set_enabled(schedule_id: str, enabled: bool) -> dict[str, Any] | None:
    return update_schedule(schedule_id, enabled=bool(enabled))


def delete_schedule(schedule_id: str) -> bool:
    path = _path(schedule_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def mark_fired(
    schedule_id: str,
    *,
    local_date: str,
    run_id: str,
) -> dict[str, Any] | None:
    """Record that today's run was started (prevents double-fire)."""
    return update_schedule(
        schedule_id,
        fired_on_date=local_date,
        last_run_at=_now(),
        last_run_id=run_id,
        last_run_status="pending",
        last_error=None,
    )


def mark_run_result(
    schedule_id: str,
    *,
    status: str,
    error: str | None = None,
) -> dict[str, Any] | None:
    return update_schedule(
        schedule_id,
        last_run_status=status,
        last_error=error,
    )
