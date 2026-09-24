"""Send LinkedIn connection requests (adapted from hexawealth_outreach).

Connect CTA locations vary by profile:
  A) Primary blue "+ Connect" button next to Message (outside More)
  B) Hidden under the "…" More menu
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Locator, Page

from profiles_store import canonicalize_profile_url


@dataclass
class ConnectResult:
    ok: bool
    outcome: str
    detail: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


async def _pause(lo: float = 0.35, hi: float = 1.0) -> None:
    await asyncio.sleep(random.uniform(lo, hi))


async def _visible_count(loc: Locator) -> int:
    try:
        return await loc.count()
    except Exception:
        return 0


async def _first_visible(loc: Locator, *, limit: int = 12) -> Locator | None:
    n = await _visible_count(loc)
    for i in range(min(n, limit)):
        item = loc.nth(i)
        try:
            if await item.is_visible(timeout=400):
                return item
        except Exception:
            continue
    return None


async def _jittered_click(target: Locator) -> bool:
    try:
        await target.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    try:
        await target.hover(timeout=2000)
        await _pause(0.1, 0.3)
        await target.click(timeout=4000)
        return True
    except Exception:
        try:
            await target.click(timeout=4000, force=True)
            return True
        except Exception:
            return False


async def _profile_actions_scope(page: Page) -> Locator:
    candidates = [
        page.locator("div.pvs-profile-actions").first,
        page.locator("section.artdeco-card").filter(
            has=page.get_by_role("button")
        ).first,
        page.locator('main[aria-label*="Profile"], main#workspace, main').first,
        page.locator("main").first,
    ]
    for loc in candidates:
        try:
            if await loc.count() > 0 and await loc.is_visible(timeout=800):
                return loc
        except Exception:
            continue
    return page.locator("body")


def _is_connect_label(label: str) -> bool:
    if not label:
        return False
    if re.search(r"\bfollow\b", label, re.I) and not re.search(
        r"\bconnect\b|\binvite\b", label, re.I
    ):
        return False
    return bool(re.search(r"\bconnect\b|\binvite\b", label, re.I))


async def _label_of(target: Locator) -> str:
    try:
        return (
            (await target.get_attribute("aria-label") or "")
            + " "
            + (await target.inner_text(timeout=800) or "")
        )
    except Exception:
        return ""


async def _detect_self_profile(page: Page, scope: Locator) -> bool:
    self_selectors = [
        'button:has-text("Edit profile")',
        'a:has-text("Edit profile")',
        'button[aria-label*="Edit profile" i]',
        'button:has-text("Add profile section")',
        'a:has-text("Add profile section")',
    ]
    for sel in self_selectors:
        try:
            if await _first_visible(page.locator(sel)) is not None:
                return True
            if await _first_visible(scope.locator(sel)) is not None:
                return True
        except Exception:
            continue
    try:
        return bool(
            await page.evaluate(
                """() => {
                  const t = (document.body && document.body.innerText) || '';
                  return /Edit profile/i.test(t) && /Add profile section/i.test(t);
                }"""
            )
        )
    except Exception:
        return False


async def _find_connect_button(page: Page, scope: Locator) -> Locator | None:
    """Find visible primary Connect CTA (outside More menu)."""

    async def _accept(target: Locator) -> Locator | None:
        if not await target.is_visible():
            return None
        return target if _is_connect_label(await _label_of(target)) else None

    roots: list[Locator | Page] = [scope, page.locator("main").first, page]
    selectors = [
        'button[aria-label*="Invite" i][aria-label*="connect" i]',
        'button[aria-label*="Connect" i]',
        'a[aria-label*="Connect" i]',
        'button.artdeco-button--primary:has-text("Connect")',
        'button.artdeco-button--2:has-text("Connect")',
        'button:has-text("+ Connect")',
        'a:has-text("+ Connect")',
        'button:has-text("Connect")',
        'a:has-text("Connect")',
    ]
    for root in roots:
        for sel in selectors:
            try:
                loc = root.locator(sel)
            except Exception:
                continue
            n = await _visible_count(loc)
            for i in range(min(n, 12)):
                accepted = await _accept(loc.nth(i))
                if accepted is not None:
                    return accepted

        for pattern in (
            re.compile(r"^\+?\s*Connect$", re.I),
            re.compile(r"Invite .* to connect", re.I),
            re.compile(r"Connect", re.I),
        ):
            try:
                loc = root.get_by_role("button", name=pattern)
            except Exception:
                continue
            n = await _visible_count(loc)
            for i in range(min(n, 10)):
                accepted = await _accept(loc.nth(i))
                if accepted is not None:
                    return accepted
    return None


async def _degree_is_first(page: Page) -> bool:
    try:
        return bool(
            await page.evaluate(
                """() => {
                  const nodes = Array.from(document.querySelectorAll('span'));
                  return nodes.some(n => {
                    const t = (n.textContent || '').trim();
                    return t === '1st' || t === '· 1st' || /^·\\s*1st$/.test(t);
                  });
                }"""
            )
        )
    except Exception:
        return False


async def _detect_invite_state(page: Page, scope: Locator) -> str | None:
    """Conservative: pending / connected / self only with clear signals."""
    if await _detect_self_profile(page, scope):
        return "self"

    for sel in (
        'button[aria-label*="Pending" i]',
        'button:has-text("Pending")',
    ):
        if await _first_visible(scope.locator(sel)) is not None:
            return "pending"
        if await _first_visible(page.locator(sel)) is not None:
            return "pending"

    for sel in (
        'button:has-text("Remove Connection")',
        'button:has-text("Remove connection")',
        'button[aria-label*="Remove connection" i]',
        'button[aria-label*="Disconnect" i]',
    ):
        if await _first_visible(scope.locator(sel)) is not None:
            return "connected"
        if await _first_visible(page.locator(sel)) is not None:
            return "connected"

    # Only treat as connected when clearly 1st AND no Connect CTA on the page.
    if await _degree_is_first(page) and await _find_connect_button(page, scope) is None:
        return "connected"
    return None


async def _open_more_menu(page: Page, scope: Locator) -> bool:
    more_selectors = [
        'button[aria-label*="More actions" i]',
        'button[aria-label*="More" i][id*="profile-overflow" i]',
        'button[id*="profile-overflow-action" i]',
        'button.artdeco-dropdown__trigger[aria-label*="More" i]',
        'button[aria-label="More"]',
    ]
    roots: list[Locator | Page] = [scope, page.locator("main").first, page]
    for root in roots:
        for sel in more_selectors:
            try:
                btn = await _first_visible(root.locator(sel))
            except Exception:
                continue
            if btn is not None and await _jittered_click(btn):
                await _pause(0.4, 0.8)
                return True
        more = await _first_visible(
            root.get_by_role("button", name=re.compile(r"^More$", re.I))
        )
        if more is not None and await _jittered_click(more):
            await _pause(0.4, 0.8)
            return True
    return False


async def _connect_from_more_menu(page: Page) -> bool:
    menu_items = [
        page.locator('div[role="menu"] button:has-text("Connect")'),
        page.locator('div[role="menu"] >> text=Connect'),
        page.locator("div.artdeco-dropdown__content button:has-text(\"Connect\")"),
        page.locator("div.artdeco-dropdown__content >> text=Connect"),
        page.locator('div.artdeco-dropdown__item:has-text("Connect")'),
        page.get_by_role("menuitem", name=re.compile(r"Connect", re.I)),
        page.get_by_role("button", name=re.compile(r"^\+?\s*Connect$", re.I)),
        page.locator('[data-test-icon="connect-small"]'),
    ]
    for loc in menu_items:
        target = await _first_visible(loc)
        if target is None:
            continue
        try:
            tag = await target.evaluate("el => el.tagName")
            if tag and tag.lower() in {"li-icon", "svg", "path", "use", "span"}:
                parent = target.locator(
                    "xpath=ancestor::*[self::button or self::div[@role='button'] "
                    "or self::div[@role='menuitem'] "
                    "or contains(@class,'artdeco-dropdown__item')][1]"
                )
                if await parent.count() > 0:
                    target = parent.first
        except Exception:
            pass
        if not _is_connect_label(await _label_of(target)):
            # text node "Connect" inside menu — still click parent if needed
            pass
        if await _jittered_click(target):
            return True
    return False


async def _send_invite_modal(page: Page) -> bool:
    await _pause(0.4, 0.9)
    modal = page.locator(
        'div[role="dialog"], div.artdeco-modal, div.send-invite'
    ).first
    has_modal = False
    try:
        has_modal = await modal.count() > 0 and await modal.is_visible(timeout=2500)
    except Exception:
        has_modal = False
    root: Page | Locator = modal if has_modal else page

    for name in (
        re.compile(r"^Send$", re.I),
        re.compile(r"^Send now$", re.I),
        re.compile(r"^Send invitation$", re.I),
        re.compile(r"^Send without a note$", re.I),
    ):
        btn = await _first_visible(root.get_by_role("button", name=name))
        if btn is not None:
            return await _jittered_click(btn)
    # Some UIs send immediately with no modal.
    return True


async def _confirm_invite_sent(page: Page, scope: Locator) -> bool:
    await _pause(0.8, 1.6)
    toast = page.locator(
        'div[data-test-artdeco-toast-item-type="success"], '
        "div.artdeco-toast-item--visible, "
        '[role="alert"]'
    )
    try:
        n = await toast.count()
        for i in range(min(n, 5)):
            text = (await toast.nth(i).inner_text(timeout=500) or "").lower()
            if any(
                x in text
                for x in ("invitation sent", "invite sent", "pending", "sent")
            ):
                return True
    except Exception:
        pass
    state = await _detect_invite_state(page, scope)
    if state == "pending":
        return True
    try:
        await page.mouse.wheel(0, 300)
    except Exception:
        pass
    await _pause(0.3, 0.6)
    return (await _detect_invite_state(page, await _profile_actions_scope(page))) == "pending"


async def resolve_session_profile_url(page: Page) -> str | None:
    try:
        await page.goto(
            "https://www.linkedin.com/in/me/",
            wait_until="domcontentloaded",
            timeout=45000,
        )
        await _pause(0.8, 1.4)
        url = page.url or ""
        if "/in/" in url and "/in/me" not in url.lower():
            return canonicalize_profile_url(url)
    except Exception:
        return None
    return None


def urls_match(a: str, b: str) -> bool:
    return canonicalize_profile_url(a) == canonicalize_profile_url(b)


async def send_connection_request(
    page: Page,
    profile_url: str,
    *,
    self_profile_url: str | None = None,
) -> ConnectResult:
    target = canonicalize_profile_url(profile_url)
    if self_profile_url and urls_match(target, self_profile_url):
        return ConnectResult(
            True, "self_profile", "Skipped — this is the logged-in session profile"
        )

    await page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
    url = page.url or ""
    if any(x in url for x in ("checkpoint", "authwall", "login", "challenge")):
        return ConnectResult(
            False, "challenged", "LinkedIn security/login wall", meta={"url": url}
        )

    current = canonicalize_profile_url(url)
    if self_profile_url and urls_match(current, self_profile_url):
        return ConnectResult(
            True, "self_profile", "Skipped — this is the logged-in session profile"
        )

    try:
        await page.wait_for_selector(
            "main, div.pvs-profile-actions, section.artdeco-card",
            timeout=12000,
        )
    except Exception:
        pass
    # Give CTAs time to hydrate (Connect / Message / More).
    await _pause(1.0, 1.8)

    scope = await _profile_actions_scope(page)
    state = await _detect_invite_state(page, scope)
    if state == "self":
        return ConnectResult(
            True, "self_profile", "Skipped — this is the logged-in session profile"
        )
    if state == "pending":
        return ConnectResult(True, "already_pending", "Invite already pending")
    if state == "connected":
        return ConnectResult(True, "already_connected", "Already connected")

    # ——— Path A: primary Connect outside More ———
    connect_btn = await _find_connect_button(page, scope)
    path = "primary"
    if connect_btn is None:
        try:
            await page.mouse.wheel(0, 400)
        except Exception:
            pass
        await _pause(0.4, 0.8)
        scope = await _profile_actions_scope(page)
        connect_btn = await _find_connect_button(page, scope)

    if connect_btn is not None:
        if not await _jittered_click(connect_btn):
            return ConnectResult(False, "error", "Failed to click primary Connect")
    else:
        # ——— Path B: Connect inside More (⋯) ———
        path = "more"
        if not await _open_more_menu(page, scope):
            return ConnectResult(
                False,
                "error",
                "Connect not visible as primary CTA and More menu not found",
            )

        # Already connected sometimes shows Remove in More
        if await _first_visible(
            page.locator(
                'div[role="menu"] >> text=Remove Connection, '
                'div.artdeco-dropdown__item:has-text("Remove Connection")'
            )
        ):
            await page.keyboard.press("Escape")
            return ConnectResult(True, "already_connected", "Already connected")

        if not await _connect_from_more_menu(page):
            await page.keyboard.press("Escape")
            # One more primary search in case More obscured it
            scope = await _profile_actions_scope(page)
            connect_btn = await _find_connect_button(page, scope)
            if connect_btn is not None:
                path = "primary_after_more"
                if not await _jittered_click(connect_btn):
                    return ConnectResult(
                        False, "error", "Failed to click Connect after More"
                    )
            else:
                state = await _detect_invite_state(page, scope)
                if state == "connected":
                    return ConnectResult(
                        True, "already_connected", "Already connected"
                    )
                if state == "self":
                    return ConnectResult(
                        True,
                        "self_profile",
                        "Skipped — this is the logged-in session profile",
                    )
                return ConnectResult(
                    False,
                    "error",
                    "Connect not found as primary button or inside More menu",
                )

    if not await _send_invite_modal(page):
        scope = await _profile_actions_scope(page)
        state = await _detect_invite_state(page, scope)
        if state == "connected":
            return ConnectResult(True, "already_connected", "Already connected")
        if state == "pending":
            return ConnectResult(True, "already_pending", "Invite already pending")
        return ConnectResult(False, "error", "Failed to confirm invite modal")

    scope = await _profile_actions_scope(page)
    confirmed = await _confirm_invite_sent(page, scope)
    if not confirmed:
        await _send_invite_modal(page)
        scope = await _profile_actions_scope(page)
        confirmed = await _confirm_invite_sent(page, scope)

    if not confirmed:
        scope = await _profile_actions_scope(page)
        state = await _detect_invite_state(page, scope)
        if state == "connected":
            return ConnectResult(True, "already_connected", "Already connected")
        if state == "pending":
            return ConnectResult(True, "already_pending", "Invite already pending")
        return ConnectResult(
            False,
            "error",
            "Connect clicked but invite not confirmed",
            meta={"path": path},
        )

    return ConnectResult(
        True,
        "sent",
        f"Connection request sent ({path})",
        meta={"path": path},
    )
