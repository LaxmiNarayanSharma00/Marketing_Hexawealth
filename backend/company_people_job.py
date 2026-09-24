"""Type 1 automation: fetch people from a Company Peoples page + full profiles."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Awaitable
from urllib.parse import urlparse

from browser import BrowserManager
from outreach_import import PersonScraper
from profiles_store import (
    canonicalize_profile_url,
    existing_profile_urls,
    profile_exists,
    save_profile,
)
from store import load_storage_state
from automations_store import append_log, update_run

logger = logging.getLogger(__name__)

PROFILE_HREF_RE = re.compile(r"/in/[A-Za-z0-9\-_%]+/?", re.I)
ProgressFn = Callable[[str], Awaitable[None] | None]


def _normalize_profile_url(href: str) -> str | None:
    if not href:
        return None
    if href.startswith("/"):
        href = "https://www.linkedin.com" + href
    parsed = urlparse(href)
    if "linkedin.com" not in (parsed.netloc or "").lower():
        return None
    m = PROFILE_HREF_RE.search(parsed.path or "")
    if not m:
        return None
    slug = m.group(0).rstrip("/")
    return canonicalize_profile_url(f"https://www.linkedin.com{slug}")


async def _human_pause(a: float = 0.8, b: float = 1.6) -> None:
    await asyncio.sleep(a + (b - a) * 0.5)


async def _collect_profile_urls(
    page,
    *,
    limit: int,
    skip_urls: set[str] | None = None,
) -> tuple[list[str], int]:
    """Collect up to `limit` NEW profile URLs. Returns (urls, skipped_known)."""
    skip = skip_urls or set()
    urls: list[str] = []
    seen: set[str] = set()
    skipped_known = 0
    for _ in range(12):
        hrefs = await page.eval_on_selector_all(
            "a[href*='/in/']",
            "els => els.map(e => e.href)",
        )
        for href in hrefs or []:
            norm = _normalize_profile_url(str(href))
            if not norm or norm in seen:
                continue
            seen.add(norm)
            if norm in skip:
                skipped_known += 1
                continue
            urls.append(norm)
            if len(urls) >= limit:
                return urls, skipped_known
        await page.mouse.wheel(0, 1800)
        await _human_pause(0.7, 1.3)
    return urls, skipped_known


def _person_to_doc(person: Any, *, meta: dict[str, Any]) -> dict[str, Any]:
    data = person.model_dump() if hasattr(person, "model_dump") else dict(person)
    linkedin_url = canonicalize_profile_url(data.get("linkedin_url") or "") or data.get(
        "linkedin_url"
    )
    return {
        "linkedin_url": linkedin_url,
        "name": data.get("name"),
        "location": data.get("location"),
        "about": data.get("about"),
        "open_to_work": bool(data.get("open_to_work")),
        "current_job_title": getattr(person, "job_title", None),
        "current_company": getattr(person, "company", None),
        "experiences": data.get("experiences") or [],
        "educations": data.get("educations") or [],
        "contacts": data.get("contacts") or [],
        "interests": data.get("interests") or [],
        "accomplishments": data.get("accomplishments") or [],
        **meta,
    }


async def run_company_people_fetch(
    *,
    run_id: str,
    session_name: str,
    company: str,
    source_link: str,
    max_connections: int,
    source_id: str = "",
    headless: bool = False,
) -> dict[str, Any]:
    async def log(msg: str) -> None:
        logger.info("[%s] %s", run_id[:8], msg)
        append_log(run_id, msg)

    update_run(run_id, status="running", error=None)
    await log(f"Starting Company People Fetch for {company}")
    await log(f"Session={session_name} · max={max_connections}")

    known = existing_profile_urls()
    await log(f"Skipping {len(known)} already-saved profile link(s)")

    storage = load_storage_state(session_name)
    found = 0
    scraped = 0
    failed = 0
    skipped = 0
    profile_ids: list[str] = []

    async with BrowserManager(headless=headless) as browser:
        await browser.load_session_state(storage)
        await log("Session cookies loaded")
        await browser.page.goto(
            "https://www.linkedin.com/feed/", wait_until="domcontentloaded"
        )
        await _human_pause(1.2, 2.0)
        url = browser.page.url or ""
        if any(x in url for x in ("checkpoint", "authwall", "login")):
            raise RuntimeError(
                "LinkedIn login/security wall. Re-login the session in Phase 1, then retry."
            )

        await log(f"Opening people page: {source_link}")
        await browser.page.goto(source_link, wait_until="domcontentloaded", timeout=60000)
        await _human_pause(1.5, 2.5)

        urls, skipped_on_page = await _collect_profile_urls(
            browser.page, limit=max_connections, skip_urls=known
        )
        skipped += skipped_on_page
        found = len(urls)
        await log(
            f"Discovered {found} new profile URL(s) "
            f"(skipped {skipped_on_page} already fetched on page)"
        )

        if not urls:
            await log("No new profiles to scrape")
        else:
            scraper = PersonScraper(browser.page)
            for i, profile_url in enumerate(urls, start=1):
                if profile_exists(profile_url):
                    skipped += 1
                    await log(f"[{i}/{found}] SKIP already saved · {profile_url}")
                    continue
                await log(f"[{i}/{found}] Scraping {profile_url}")
                try:
                    person = await scraper.scrape(
                        profile_url,
                        include_interests=False,
                        include_accomplishments=False,
                    )
                    saved = save_profile(
                        _person_to_doc(
                            person,
                            meta={
                                "source_company": company,
                                "source_id": source_id,
                                "automation_id": run_id,
                                "session_name": session_name,
                            },
                        )
                    )
                    scraped += 1
                    known.add(canonicalize_profile_url(profile_url))
                    profile_ids.append(saved["id"])
                    await log(
                        f"  OK {person.name or '(no name)'} · "
                        f"{len(person.experiences)} exp · {len(person.educations)} edu"
                    )
                except Exception as exc:
                    failed += 1
                    await log(f"  FAILED: {exc}")
                    page_url = browser.page.url or ""
                    if any(x in page_url for x in ("checkpoint", "authwall", "login")):
                        raise RuntimeError(
                            "LinkedIn security page during scrape. Re-login and retry."
                        ) from exc
                await _human_pause(2.0, 3.5)

    result = {
        "found": found,
        "scraped": scraped,
        "failed": failed,
        "skipped": skipped,
        "profile_ids": profile_ids,
    }
    update_run(run_id, status="done", result=result)
    await log(f"Done · scraped={scraped} skipped={skipped} failed={failed}")
    return result
