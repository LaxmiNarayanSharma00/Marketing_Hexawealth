"""Type 3 automation: like / comment / repost latest brand posts across sessions."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from browser import BrowserManager
from engage_actions import engage_post, find_latest_post
from engagement_store import has_engaged, mark_engaged
from store import list_sessions, load_storage_state
from automations_store import append_log, update_run

logger = logging.getLogger(__name__)

# Fixed brand / founder feeds — latest post on each is engaged once per session.
ENGAGE_SOURCES: list[tuple[str, str]] = [
    ("Hexawealth", "https://www.linkedin.com/company/hexawealth/posts/"),
    ("Abhinav Singhvi", "https://www.linkedin.com/in/abhinav-singhvi-1a429233/"),
    (
        "Abhinav Swaroop",
        "https://www.linkedin.com/in/abhinav-swaroop-cfa-8002a015/",
    ),
    (
        "Vinayak Gandhi",
        "https://www.linkedin.com/in/vinayak-gandhi-cfa-b7559b194/",
    ),
]


def _logged_in_sessions() -> list[str]:
    names: list[str] = []
    for s in list_sessions():
        if s.get("has_storage_state"):
            names.append(s["name"])
    return names


async def run_brand_engage(
    *,
    run_id: str,
    headless: bool = False,
) -> dict[str, Any]:
    async def log(msg: str) -> None:
        logger.info("[%s] %s", run_id[:8], msg)
        append_log(run_id, msg)

    update_run(run_id, status="running", error=None)
    await log("Starting Brand Engage")
    await log(
        "Actions per latest post: Like → comment “Insightful” → Repost"
    )

    sessions = _logged_in_sessions()
    if not sessions:
        update_run(
            run_id,
            status="error",
            error="No logged-in sessions. Complete Phase 1 login first.",
        )
        await log("Stopped — no logged-in sessions")
        return {"sessions": 0, "engaged": 0, "skipped": 0, "failed": 0}

    await log(f"Sessions to run: {', '.join(sessions)}")
    await log(f"Sources: {len(ENGAGE_SOURCES)}")

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
                failed += len(ENGAGE_SOURCES)
                await log(
                    "  STOPPED session — LinkedIn login/security wall. Re-login in Phase 1."
                )
                continue

            for label, source_url in ENGAGE_SOURCES:
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

                    result = await engage_post(browser.page, post)
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
        "sources": len(ENGAGE_SOURCES),
        "pairs": total_pairs,
        "engaged": engaged,
        "skipped": skipped,
        "failed": failed,
    }
    update_run(run_id, status="done", result=result)
    await log(
        f"Done · engaged={engaged} skipped={skipped} failed={failed} "
        f"(sessions={len(sessions)})"
    )
    return result
