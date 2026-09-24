"""Type 3 automation: like / comment / repost latest brand posts across sessions."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Iterable

from browser import BrowserManager
from engage_actions import engage_post, find_latest_post
from engagement_store import has_engaged, mark_engaged
from store import list_sessions, load_storage_state
from automations_store import append_log, update_run

logger = logging.getLogger(__name__)

ALL_ACTIONS = ("like", "comment", "repost")

# Fixed brand / founder feeds — latest post on each is engaged once per session.
ENGAGE_SOURCES: list[dict[str, str]] = [
    {
        "id": "hexawealth",
        "label": "Hexawealth",
        "url": "https://www.linkedin.com/company/hexawealth/posts/",
    },
    {
        "id": "abhinav-singhvi",
        "label": "Abhinav Singhvi",
        "url": "https://www.linkedin.com/in/abhinav-singhvi-1a429233/",
    },
    {
        "id": "abhinav-swaroop",
        "label": "Abhinav Swaroop",
        "url": "https://www.linkedin.com/in/abhinav-swaroop-cfa-8002a015/",
    },
    {
        "id": "vinayak-gandhi",
        "label": "Vinayak Gandhi",
        "url": "https://www.linkedin.com/in/vinayak-gandhi-cfa-b7559b194/",
    },
]

_SOURCE_BY_URL = {s["url"].rstrip("/").lower(): s for s in ENGAGE_SOURCES}
_SOURCE_BY_ID = {s["id"]: s for s in ENGAGE_SOURCES}


def normalize_actions(actions: Iterable[str] | None) -> list[str]:
    if not actions:
        return list(ALL_ACTIONS)
    out: list[str] = []
    for a in actions:
        key = (a or "").strip().lower()
        if key in ALL_ACTIONS and key not in out:
            out.append(key)
    if not out:
        raise ValueError("actions must include at least one of: like, comment, repost")
    return out


def resolve_sources(
    source_ids: Iterable[str] | None = None,
    source_urls: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    """Resolve selected brand audiences. Empty selection → all four."""
    if source_ids:
        rows: list[dict[str, str]] = []
        for sid in source_ids:
            src = _SOURCE_BY_ID.get((sid or "").strip())
            if not src:
                raise ValueError(f"Unknown brand source id: {sid}")
            if src not in rows:
                rows.append(src)
        return rows
    if source_urls:
        rows = []
        for url in source_urls:
            key = (url or "").strip().rstrip("/").lower()
            src = _SOURCE_BY_URL.get(key)
            if not src:
                # Allow exact match with trailing slash variants already normalized.
                for candidate in ENGAGE_SOURCES:
                    if candidate["url"].rstrip("/").lower() == key:
                        src = candidate
                        break
            if not src:
                raise ValueError(f"Unknown brand source url: {url}")
            if src not in rows:
                rows.append(src)
        return rows
    return list(ENGAGE_SOURCES)


def _logged_in_sessions() -> list[str]:
    names: list[str] = []
    for s in list_sessions():
        if s.get("has_storage_state"):
            names.append(s["name"])
    return names


async def run_brand_engage(
    *,
    run_id: str,
    session_name: str | None = None,
    source_ids: list[str] | None = None,
    source_urls: list[str] | None = None,
    actions: list[str] | None = None,
    headless: bool = False,
) -> dict[str, Any]:
    async def log(msg: str) -> None:
        logger.info("[%s] %s", run_id[:8], msg)
        append_log(run_id, msg)

    sources = resolve_sources(source_ids=source_ids, source_urls=source_urls)
    action_list = normalize_actions(actions)
    action_set = set(action_list)

    update_run(run_id, status="running", error=None)
    await log("Starting Brand Engage")
    await log(f"Actions: {', '.join(action_list)}")
    await log(
        "Audiences: " + ", ".join(s["label"] for s in sources)
    )

    all_logged_in = _logged_in_sessions()
    if session_name and session_name != "all":
        if session_name not in all_logged_in:
            update_run(
                run_id,
                status="error",
                error=f"Session '{session_name}' is not logged in.",
            )
            await log(f"Stopped — session {session_name} not logged in")
            return {"sessions": 0, "engaged": 0, "skipped": 0, "failed": 0}
        sessions = [session_name]
    else:
        sessions = all_logged_in

    if not sessions:
        update_run(
            run_id,
            status="error",
            error="No logged-in sessions. Complete Phase 1 login first.",
        )
        await log("Stopped — no logged-in sessions")
        return {"sessions": 0, "engaged": 0, "skipped": 0, "failed": 0}

    await log(f"Sessions to run: {', '.join(sessions)}")
    await log(f"Sources: {len(sources)}")

    engaged = 0
    skipped = 0
    failed = 0
    total_pairs = 0

    for session_name in sessions:
        await log(f"—— Session {session_name} ——")
        try:
            storage = load_storage_state(session_name)
        except FileNotFoundError as exc:
            failed += 1
            await log(f"  SKIP session (no cookies): {exc}")
            continue

        async with BrowserManager(headless=headless) as browser:
            await browser.load_session_state(storage)
            await log("  Cookies loaded")
            await browser.page.goto(
                "https://www.linkedin.com/feed/", wait_until="domcontentloaded"
            )
            await asyncio.sleep(random.uniform(1.0, 1.8))
            url = browser.page.url or ""
            if any(x in url for x in ("checkpoint", "authwall", "login")):
                failed += len(sources)
                await log(
                    "  STOPPED session — LinkedIn login/security wall. Re-login in Phase 1."
                )
                continue

            for src in sources:
                label = src["label"]
                source_url = src["url"]
                total_pairs += 1
                await log(f"  [{label}] Finding latest post…")
                try:
                    post = await find_latest_post(browser.page, source_url)
                    if not post:
                        failed += 1
                        await log(f"  [{label}] FAILED · no post found")
                        continue

                    preview = (post.preview or "")[:70]
                    await log(
                        f"  [{label}] Latest · {post.post_urn}"
                        + (f" · “{preview}…”" if preview else "")
                    )

                    if has_engaged(session_name, post.post_urn):
                        skipped += 1
                        await log(
                            f"  [{label}] SKIP · already engaged this post (idempotent)"
                        )
                        continue

                    result = await engage_post(
                        browser.page, post, actions=action_set
                    )
                    mark_engaged(
                        session_name=session_name,
                        post_urn=post.post_urn,
                        post_url=post.post_url,
                        source_url=source_url,
                        liked=result.liked,
                        commented=result.commented,
                        reposted=result.reposted,
                        note=result.detail,
                    )
                    if result.ok:
                        engaged += 1
                        await log(f"  [{label}] OK · {result.detail}")
                    else:
                        failed += 1
                        await log(
                            f"  [{label}] FAILED {result.outcome} · {result.detail}"
                        )
                except Exception as exc:
                    failed += 1
                    await log(f"  [{label}] FAILED: {exc}")

                await asyncio.sleep(random.uniform(2.0, 4.0))

        await asyncio.sleep(random.uniform(1.0, 2.0))

    result = {
        "sessions": len(sessions),
        "sources": len(sources),
        "pairs": total_pairs,
        "engaged": engaged,
        "skipped": skipped,
        "failed": failed,
        "actions": action_list,
        "source_ids": [s["id"] for s in sources],
    }
    update_run(run_id, status="done", result=result)
    await log(
        f"Done · engaged={engaged} skipped={skipped} failed={failed} "
        f"(sessions={len(sessions)})"
    )
    return result
