"""SQLite-backed LinkedIn session store (Playwright storage_state)."""

from __future__ import annotations

from typing import Any

from db import dumps, ensure_db, get_db, loads, now


def _safe_name(name: str) -> str:
    safe = "".join(c for c in name.strip() if c.isalnum() or c in "-_").strip("-_")
    if not safe:
        raise ValueError("invalid session name")
    return safe


def ensure_dir() -> None:
    ensure_db()


def _row_to_doc(row: Any) -> dict[str, Any]:
    return {
        "name": row["name"],
        "status": row["status"] or "missing",
        "storage_state": loads(row["storage_state"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_sessions() -> list[dict[str, Any]]:
    ensure_db()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [public_view(_row_to_doc(r)) for r in rows]


def get_session(name: str) -> dict[str, Any] | None:
    ensure_db()
    safe = _safe_name(name)
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE name = ?", (safe,)
        ).fetchone()
    return _row_to_doc(row) if row else None


def get_session_public(name: str) -> dict[str, Any] | None:
    doc = get_session(name)
    return public_view(doc) if doc else None


def create_session(name: str) -> dict[str, Any]:
    ensure_db()
    safe = _safe_name(name)
    ts = now()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM sessions WHERE name = ?", (safe,)
        ).fetchone()
        if existing:
            raise FileExistsError(f"session '{name}' already exists")
        conn.execute(
            """
            INSERT INTO sessions(name, status, storage_state, created_at, updated_at)
            VALUES (?, 'missing', '{}', ?, ?)
            """,
            (safe, ts, ts),
        )
    return public_view(
        {
            "name": safe,
            "status": "missing",
            "storage_state": {},
            "created_at": ts,
            "updated_at": ts,
        }
    )


def save_storage_state(name: str, storage_state: dict[str, Any]) -> dict[str, Any]:
    ensure_db()
    safe = _safe_name(name)
    ts = now()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE name = ?", (safe,)
        ).fetchone()
        if row:
            created = row["created_at"]
            conn.execute(
                """
                UPDATE sessions
                SET storage_state = ?, status = 'present', updated_at = ?
                WHERE name = ?
                """,
                (dumps(storage_state), ts, safe),
            )
        else:
            created = ts
            conn.execute(
                """
                INSERT INTO sessions(name, status, storage_state, created_at, updated_at)
                VALUES (?, 'present', ?, ?, ?)
                """,
                (safe, dumps(storage_state), ts, ts),
            )
    return public_view(
        {
            "name": safe,
            "status": "present",
            "storage_state": storage_state,
            "created_at": created,
            "updated_at": ts,
        }
    )


def set_status(name: str, status: str) -> None:
    ensure_db()
    safe = _safe_name(name)
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET status = ?, updated_at = ? WHERE name = ?",
            (status, now(), safe),
        )


def delete_session(name: str) -> bool:
    ensure_db()
    safe = _safe_name(name)
    with get_db() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE name = ?", (safe,))
        return cur.rowcount > 0


def load_storage_state(name: str) -> dict[str, Any]:
    doc = get_session(name)
    if not doc or not (doc.get("storage_state") or {}).get("cookies"):
        raise FileNotFoundError(f"no saved LinkedIn cookies for session '{name}'")
    return doc["storage_state"]


def validate_storage_state(storage_state: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate a Playwright storage_state payload for import."""
    if not isinstance(storage_state, dict):
        raise ValueError("storage_state must be a JSON object")

    # Allow wrapping { "storage_state": { ... } } from export helpers
    if "cookies" not in storage_state and isinstance(
        storage_state.get("storage_state"), dict
    ):
        storage_state = storage_state["storage_state"]

    cookies = storage_state.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        raise ValueError("storage_state.cookies must be a non-empty array")

    normalized: list[dict[str, Any]] = []
    for i, cookie in enumerate(cookies):
        if not isinstance(cookie, dict):
            raise ValueError(f"cookie[{i}] must be an object")
        name = cookie.get("name")
        value = cookie.get("value")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"cookie[{i}].name is required")
        if value is None or (isinstance(value, str) and not value):
            raise ValueError(f"cookie[{i}].value is required")
        entry = dict(cookie)
        entry.setdefault("domain", ".linkedin.com")
        entry.setdefault("path", "/")
        normalized.append(entry)

    names = {c.get("name") for c in normalized}
    if "li_at" not in names:
        raise ValueError(
            "missing li_at cookie — export after a full LinkedIn login, "
            "or paste a complete Playwright storage_state"
        )

    origins = storage_state.get("origins")
    if origins is None:
        origins = []
    elif not isinstance(origins, list):
        raise ValueError("storage_state.origins must be an array when present")

    return {"cookies": normalized, "origins": origins}


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
