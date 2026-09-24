"""SQLite-backed automation schedule mappings.

Supports:
  - company_people_fetch / build_connection: session → source, max, daily time
  - brand_engage: audiences (brand sources) + actions + daily time (all sessions)
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from db import dumps, ensure_db, get_db, loads, now

KIND_COMPANY_PEOPLE = "company_people_fetch"
KIND_BUILD_CONNECTION = "build_connection"
KIND_BRAND_ENGAGE = "brand_engage"

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def ensure_dir() -> None:
    ensure_db()


def normalize_run_time(value: str) -> str:
    raw = (value or "").strip()
    if len(raw) >= 8 and raw[2] == ":" and raw[5] == ":":
        raw = raw[:5]
    if not _TIME_RE.match(raw):
        raise ValueError("run_time must be HH:MM in 24-hour local time")
    return raw


def _row_to_doc(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "session_name": row["session_name"] or "",
        "source_id": row["source_id"] or "",
        "company": row["company"] or "",
        "source_link": row["source_link"] or "",
        "max_profiles": int(row["max_profiles"] or 0),
        "source_ids": loads(row["source_ids"], []),
        "actions": loads(row["actions"], []),
        "run_time": row["run_time"] or "09:00",
        "enabled": bool(row["enabled"]),
        "last_run_at": row["last_run_at"],
        "last_run_id": row["last_run_id"],
        "last_run_status": row["last_run_status"],
        "last_error": row["last_error"],
        "fired_on_date": row["fired_on_date"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def public_view(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc["id"],
        "kind": doc.get("kind", KIND_COMPANY_PEOPLE),
        "session_name": doc.get("session_name", ""),
        "source_id": doc.get("source_id", ""),
        "company": doc.get("company", ""),
        "source_link": doc.get("source_link", ""),
        "max_profiles": int(doc.get("max_profiles") or 0),
        "source_ids": list(doc.get("source_ids") or []),
        "actions": list(doc.get("actions") or []),
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
    ensure_db()
    with get_db() as conn:
        if kind:
            rows = conn.execute(
                "SELECT * FROM schedules WHERE kind = ? ORDER BY created_at DESC",
                (kind,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM schedules ORDER BY created_at DESC"
            ).fetchall()
    return [public_view(_row_to_doc(r)) for r in rows]


def get_schedule(schedule_id: str) -> dict[str, Any] | None:
    ensure_db()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
    return _row_to_doc(row) if row else None


def get_schedule_public(schedule_id: str) -> dict[str, Any] | None:
    doc = get_schedule(schedule_id)
    return public_view(doc) if doc else None


def create_schedule(
    *,
    kind: str,
    session_name: str = "",
    source_id: str = "",
    company: str = "",
    source_link: str = "",
    max_profiles: int = 10,
    run_time: str = "09:00",
    enabled: bool = True,
    source_ids: list[str] | None = None,
    actions: list[str] | None = None,
) -> dict[str, Any]:
    ensure_db()
    if kind == KIND_BRAND_ENGAGE:
        max_profiles = 0
    elif max_profiles < 1 or max_profiles > 100:
        raise ValueError("max_profiles must be between 1 and 100")
    run_time = normalize_run_time(run_time)
    schedule_id = str(uuid.uuid4())
    ts = now()
    doc = {
        "id": schedule_id,
        "kind": kind,
        "session_name": session_name,
        "source_id": source_id,
        "company": company,
        "source_link": source_link,
        "max_profiles": max_profiles,
        "source_ids": list(source_ids or []),
        "actions": list(actions or []),
        "run_time": run_time,
        "enabled": enabled,
        "last_run_at": None,
        "last_run_id": None,
        "last_run_status": None,
        "last_error": None,
        "fired_on_date": None,
        "created_at": ts,
        "updated_at": ts,
    }
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO schedules(
                id, kind, session_name, source_id, company, source_link, max_profiles,
                source_ids, actions, run_time, enabled, last_run_at, last_run_id,
                last_run_status, last_error, fired_on_date, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?)
            """,
            (
                schedule_id,
                kind,
                session_name,
                source_id,
                company,
                source_link,
                max_profiles,
                dumps(doc["source_ids"]),
                dumps(doc["actions"]),
                run_time,
                1 if enabled else 0,
                ts,
                ts,
            ),
        )
    return public_view(doc)


def update_schedule(schedule_id: str, **fields: Any) -> dict[str, Any] | None:
    ensure_db()
    if "run_time" in fields and fields["run_time"] is not None:
        fields["run_time"] = normalize_run_time(str(fields["run_time"]))
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        if not row:
            return None
        doc = _row_to_doc(row)
        if "max_profiles" in fields and fields["max_profiles"] is not None:
            n = int(fields["max_profiles"])
            if doc.get("kind") != KIND_BRAND_ENGAGE and (n < 1 or n > 100):
                raise ValueError("max_profiles must be between 1 and 100")
            fields["max_profiles"] = n
        if "source_ids" in fields and fields["source_ids"] is not None:
            fields["source_ids"] = list(fields["source_ids"])
        if "actions" in fields and fields["actions"] is not None:
            fields["actions"] = list(fields["actions"])

        allowed = {
            "kind",
            "session_name",
            "source_id",
            "company",
            "source_link",
            "max_profiles",
            "source_ids",
            "actions",
            "run_time",
            "enabled",
            "last_run_at",
            "last_run_id",
            "last_run_status",
            "last_error",
            "fired_on_date",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        cols: list[str] = []
        vals: list[Any] = []
        for key, value in updates.items():
            if key in ("source_ids", "actions"):
                cols.append(f"{key} = ?")
                vals.append(dumps(value if value is not None else []))
            elif key == "enabled":
                cols.append("enabled = ?")
                vals.append(1 if value else 0)
            else:
                cols.append(f"{key} = ?")
                vals.append(value)
        ts = now()
        cols.append("updated_at = ?")
        vals.append(ts)
        vals.append(schedule_id)
        conn.execute(
            f"UPDATE schedules SET {', '.join(cols)} WHERE id = ?",
            vals,
        )
        row = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        return public_view(_row_to_doc(row))


def set_enabled(schedule_id: str, enabled: bool) -> dict[str, Any] | None:
    return update_schedule(schedule_id, enabled=bool(enabled))


def delete_schedule(schedule_id: str) -> bool:
    ensure_db()
    with get_db() as conn:
        cur = conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        return cur.rowcount > 0


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
        last_run_at=now(),
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
