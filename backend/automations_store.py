"""SQLite-backed automation runs."""

from __future__ import annotations

import uuid
from typing import Any

from db import dumps, ensure_db, get_db, loads, now

AUTOMATION_KIND_COMPANY_PEOPLE = "company_people_fetch"
AUTOMATION_KIND_BUILD_CONNECTION = "build_connection"
AUTOMATION_KIND_BRAND_ENGAGE = "brand_engage"
KIND_LABELS = {
    AUTOMATION_KIND_COMPANY_PEOPLE: "Company People Fetch",
    AUTOMATION_KIND_BUILD_CONNECTION: "Build Connection",
    AUTOMATION_KIND_BRAND_ENGAGE: "Brand Engage",
}


def ensure_dir() -> None:
    ensure_db()


def _logs_for(conn: Any, run_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT message FROM run_logs WHERE run_id = ? ORDER BY id ASC",
        (run_id,),
    ).fetchall()
    return [r["message"] for r in rows]


def _row_to_doc(conn: Any, row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "session_name": row["session_name"] or "",
        "company": row["company"] or "",
        "source_id": row["source_id"] or "",
        "source_link": row["source_link"] or "",
        "schedule_id": row["schedule_id"],
        "trigger": row["trigger"] or "manual",
        "max_connections": int(row["max_connections"] or 0),
        "max_requests": int(row["max_requests"] or 0),
        "status": row["status"] or "pending",
        "logs": _logs_for(conn, row["id"]),
        "error": row["error"],
        "result": loads(row["result"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


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
        "schedule_id": doc.get("schedule_id") or None,
        "trigger": doc.get("trigger") or "manual",
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
    ensure_db()
    with get_db() as conn:
        if kind:
            rows = conn.execute(
                "SELECT * FROM runs WHERE kind = ? ORDER BY created_at DESC",
                (kind,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC"
            ).fetchall()
        return [public_view(_row_to_doc(conn, r)) for r in rows]


def get_run(run_id: str) -> dict[str, Any] | None:
    ensure_db()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        return _row_to_doc(conn, row)


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
    schedule_id: str | None = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    ensure_db()
    run_id = str(uuid.uuid4())
    req = max_requests if max_requests is not None else max_connections
    ts = now()
    doc = {
        "id": run_id,
        "kind": kind,
        "session_name": session_name,
        "company": company,
        "source_id": source_id,
        "source_link": source_link,
        "schedule_id": schedule_id,
        "trigger": trigger or "manual",
        "max_connections": max_connections or req,
        "max_requests": req,
        "status": "pending",
        "logs": [],
        "error": None,
        "result": {},
        "created_at": ts,
        "updated_at": ts,
    }
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO runs(
                id, kind, session_name, company, source_id, source_link, schedule_id,
                trigger, max_connections, max_requests, status, error, result,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '{}', ?, ?)
            """,
            (
                run_id,
                kind,
                session_name,
                company,
                source_id,
                source_link,
                schedule_id,
                trigger or "manual",
                max_connections or req,
                req,
                "pending",
                ts,
                ts,
            ),
        )
    return public_view(doc)


def append_log(run_id: str, msg: str) -> None:
    ensure_db()
    ts = now()
    with get_db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if not exists:
            return
        conn.execute(
            "INSERT INTO run_logs(run_id, message, created_at) VALUES (?, ?, ?)",
            (run_id, msg, ts),
        )
        conn.execute(
            "UPDATE runs SET updated_at = ? WHERE id = ?",
            (ts, run_id),
        )


def update_run(run_id: str, **fields: Any) -> dict[str, Any] | None:
    ensure_db()
    allowed = {
        "kind",
        "session_name",
        "company",
        "source_id",
        "source_link",
        "schedule_id",
        "trigger",
        "max_connections",
        "max_requests",
        "status",
        "error",
        "result",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if "logs" in fields:
        # Full replace of logs (rare); rewrite run_logs.
        pass
    ts = now()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        if "logs" in fields:
            conn.execute("DELETE FROM run_logs WHERE run_id = ?", (run_id,))
            for msg in fields.get("logs") or []:
                conn.execute(
                    "INSERT INTO run_logs(run_id, message, created_at) VALUES (?, ?, ?)",
                    (run_id, str(msg), ts),
                )
        cols: list[str] = []
        vals: list[Any] = []
        for key, value in updates.items():
            if key == "result":
                cols.append("result = ?")
                vals.append(dumps(value if value is not None else {}))
            else:
                cols.append(f"{key} = ?")
                vals.append(value)
        cols.append("updated_at = ?")
        vals.append(ts)
        vals.append(run_id)
        conn.execute(
            f"UPDATE runs SET {', '.join(cols)} WHERE id = ?",
            vals,
        )
        row = conn.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        return public_view(_row_to_doc(conn, row))
