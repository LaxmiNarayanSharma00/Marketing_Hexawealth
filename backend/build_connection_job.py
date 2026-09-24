"""Type 2 automation: send connection requests to stored profiles."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from browser import BrowserManager
from connect_actions import resolve_session_profile_url, send_connection_request, urls_match
from profiles_store import list_profiles_for_connect, update_connection_status
from store import load_storage_state
from automations_store import append_log, update_run

logger = logging.getLogger(__name__)

SKIP_OUTCOMES = {
    "already_pending": ("pending", "Invite already pending"),
    "already_connected": ("connected", "Already connected"),
    "self_profile": ("self", "Session's own profile"),
}


async def run_build_connection(
    *,
    run_id: str,
    session_name: str,
    max_requests: int,
    headless: bool = False,
) -> dict[str, Any]:
    async def log(msg: str) -> None:
        logger.info("[%s] %s", run_id[:8], msg)
        append_log(run_id, msg)

    update_run(run_id, status="running", error=None)
    await log("Starting Build Connection")
    await log(f"Session={session_name} · max_requests={max_requests}")

    # Fetch extra candidates so self / already-handled ones don't shrink the batch.
    pool = list_profiles_for_connect(limit=max(max_requests * 3, max_requests + 5))
    await log(f"Loaded {len(pool)} candidate profile(s) from store")

    storage = load_storage_state(session_name)
    sent = 0
    skipped = 0
    failed = 0
    selected = 0

    async with BrowserManager(headless=headless) as browser:
        await browser.load_session_state(storage)
        await log("Session cookies loaded")
        await browser.page.goto(
            "https://www.linkedin.com/feed/", wait_until="domcontentloaded"
        )
        await asyncio.sleep(random.uniform(1.2, 2.0))
        url = browser.page.url or ""
        if any(x in url for x in ("checkpoint", "authwall", "login")):
            # Soft-fail the whole run without crashing the API task handler mid-loop.
            update_run(
                run_id,
                status="error",
                error="LinkedIn login/security wall. Re-login in Phase 1, then retry.",
            )
            await log("Stopped — LinkedIn login/security wall on feed")
            return {"selected": 0, "sent": 0, "skipped": 0, "failed": 0}

        self_url = await resolve_session_profile_url(browser.page)
        if self_url:
            await log(f"Session profile detected: {self_url}")
            # Mark + drop self from store candidates immediately
            for p in list(pool):
                if urls_match(p.get("linkedin_url") or "", self_url):
                    update_connection_status(
                        p["linkedin_url"],
                        "self",
                        note="Logged-in session profile",
                    )
                    pool = [
                        x
                        for x in pool
                        if not urls_match(x.get("linkedin_url") or "", self_url)
                    ]
                    skipped += 1
                    await log("  Pre-skip session's own profile in candidates")
                    break
        else:
            await log("Could not resolve session profile URL — will detect per page")

        candidates = pool[:max_requests]
        selected = len(candidates)
        await log(f"Will attempt {selected} connection request(s)")

        if not candidates:
            result = {
                "selected": 0,
                "sent": sent,
                "skipped": skipped,
                "failed": failed,
            }
            update_run(run_id, status="done", result=result)
            await log("No eligible profiles left after filtering")
            return result

        for i, profile in enumerate(candidates, start=1):
            profile_url = profile.get("linkedin_url") or ""
            name = profile.get("name") or profile_url
            await log(f"[{i}/{selected}] Connect → {name}")
            try:
                result = await send_connection_request(
                    browser.page,
                    profile_url,
                    self_profile_url=self_url,
                )
                if result.outcome == "sent":
                    sent += 1
                    update_connection_status(
                        profile_url, "pending", note=result.detail
                    )
                    await log(f"  OK sent · {result.detail}")
                elif result.outcome in SKIP_OUTCOMES:
                    skipped += 1
                    status, label = SKIP_OUTCOMES[result.outcome]
                    update_connection_status(
                        profile_url, status, note=result.detail or label
                    )
                    await log(f"  SKIP {result.outcome} · {result.detail}")
                elif result.outcome == "challenged":
                    failed += 1
                    update_connection_status(
                        profile_url, "error", note=result.detail
                    )
                    await log(
                        f"  FAILED challenged · {result.detail} "
                        "(continuing remaining profiles)"
                    )
                    # Try to recover to feed; do not abort the batch.
                    try:
                        await browser.page.goto(
                            "https://www.linkedin.com/feed/",
                            wait_until="domcontentloaded",
                        )
                        await asyncio.sleep(1.0)
                    except Exception:
                        pass
                else:
                    failed += 1
                    update_connection_status(
                        profile_url, "error", note=result.detail
                    )
                    await log(f"  FAILED {result.outcome} · {result.detail}")
            except Exception as exc:
                failed += 1
                update_connection_status(profile_url, "error", note=str(exc))
                await log(f"  FAILED: {exc} (continuing)")
                try:
                    await browser.page.goto(
                        "https://www.linkedin.com/feed/",
                        wait_until="domcontentloaded",
                    )
                except Exception:
                    pass
            await asyncio.sleep(random.uniform(2.5, 4.5))

    result = {
        "selected": selected,
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
    }
    update_run(run_id, status="done", result=result)
    await log(f"Done · sent={sent} skipped={skipped} failed={failed}")
    return result
