"""Idempotent record of posts already liked/commented/reposted per session."""

from __future__ import annotations

import re
from typing import Any

from db import ensure_db, get_db, now

_ACTIVITY_URN_RE = re.compile(
    r"(urn:li:(?:activity|ugcPost|share):\d+)", re.I
)


def ensure_dir() -> None:
    ensure_db()


def canonicalize_post_urn(urn_or_url: str) -> str:
    raw = (urn_or_url or "").strip()
    # SDUI company cards have no activity URN. Keep the componentkey case
    # so the later [componentkey="..."] lookup stays exact.
    if raw.lower().startswith("sdui:"):
        return "sdui:" + raw.split(":", 1)[1]
    m = _ACTIVITY_URN_RE.search(raw)
    if m:
        return m.group(1).lower()
    cleaned = raw.split("?")[0].split("#")[0].rstrip("/").lower()
    return cleaned


def _row_to_doc(row: Any) -> dict[str, Any]:
    return {
        "session_name": row["session_name"],
        "post_urn": row["post_urn"],
        "post_url": row["post_url"] or "",
        "source_url": row["source_url"] or "",
        "liked": bool(row["liked"]),
        "commented": bool(row["commented"]),
        "reposted": bool(row["reposted"]),
        "done": bool(row["done"]),
        "note": row["note"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def has_engaged(session_name: str, post_urn: str) -> bool:
    ensure_db()
    urn = canonicalize_post_urn(post_urn)
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT done FROM engagements
            WHERE session_name = ? AND post_urn = ?
            """,
            (session_name, urn),
        ).fetchone()
    if not row:
        return False
    return bool(row["done"])


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
    ensure_db()
    urn = canonicalize_post_urn(post_urn)
    ts = now()
    with get_db() as conn:
        prev = conn.execute(
            """
            SELECT * FROM engagements
            WHERE session_name = ? AND post_urn = ?
            """,
            (session_name, urn),
        ).fetchone()
        if prev:
            liked_v = bool(prev["liked"] or liked)
            commented_v = bool(prev["commented"] or commented)
            reposted_v = bool(prev["reposted"] or reposted)
            done = bool(liked_v and commented_v and reposted_v)
            created = prev["created_at"] or ts
            conn.execute(
                """
                UPDATE engagements SET
                    post_url = ?, source_url = ?, liked = ?, commented = ?,
                    reposted = ?, done = ?, note = ?, updated_at = ?
                WHERE session_name = ? AND post_urn = ?
                """,
                (
                    post_url or prev["post_url"] or "",
                    source_url or prev["source_url"] or "",
                    1 if liked_v else 0,
                    1 if commented_v else 0,
                    1 if reposted_v else 0,
                    1 if done else 0,
                    note or prev["note"] or "",
                    ts,
                    session_name,
                    urn,
                ),
            )
        else:
            liked_v = liked
            commented_v = commented
            reposted_v = reposted
            done = bool(liked_v and commented_v and reposted_v)
            created = ts
            conn.execute(
                """
                INSERT INTO engagements(
                    session_name, post_urn, post_url, source_url, liked, commented,
                    reposted, done, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_name,
                    urn,
                    post_url,
                    source_url,
                    1 if liked_v else 0,
                    1 if commented_v else 0,
                    1 if reposted_v else 0,
                    1 if done else 0,
                    note,
                    ts,
                    ts,
                ),
            )
    return {
        "session_name": session_name,
        "post_urn": urn,
        "post_url": post_url,
        "source_url": source_url,
        "liked": liked_v,
        "commented": commented_v,
        "reposted": reposted_v,
        "done": done,
        "note": note,
        "created_at": created,
        "updated_at": ts,
    }


def get_engagement(session_name: str, post_urn: str) -> dict[str, Any] | None:
    ensure_db()
    urn = canonicalize_post_urn(post_urn)
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM engagements
            WHERE session_name = ? AND post_urn = ?
            """,
            (session_name, urn),
        ).fetchone()
    return _row_to_doc(row) if row else None
