"""Minimal Playwright browser helper for LinkedIn login + session export."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

logger = logging.getLogger(__name__)

# Large viewport so LinkedIn feed cards (and social action bars) actually mount.
# A minimised / tiny window often yields zero posts — lazy content never loads.
VIEWPORT = {"width": 1440, "height": 960}

AUTH_BLOCKERS = (
    "/login",
    "/authwall",
    "/checkpoint",
    "/challenge",
    "/uas/login",
    "/uas/consumer-email-challenge",
)
AUTH_PAGES = ("/feed", "/mynetwork", "/messaging", "/notifications")


async def is_logged_in(page: Page) -> bool:
    try:
        url = page.url or ""
        if any(p in url for p in AUTH_BLOCKERS):
            return False
        old = await page.locator(
            '.global-nav__primary-link, [data-control-name="nav.settings"]'
        ).count()
        new = await page.locator(
            'nav a[href*="/feed"], nav button:has-text("Home"), nav a[href*="/mynetwork"]'
        ).count()
        on_app = any(p in url for p in AUTH_PAGES)
        return old > 0 or new > 0 or on_app
    except Exception:
        return False


async def wait_for_manual_login(page: Page, timeout_ms: int = 300_000) -> None:
    start = asyncio.get_event_loop().time()
    while True:
        if await is_logged_in(page):
            return
        if (asyncio.get_event_loop().time() - start) * 1000 > timeout_ms:
            raise TimeoutError(
                "Manual login timed out. Finish LinkedIn login in the browser window."
            )
        await asyncio.sleep(1)


async def _maximize_page(page: Page) -> None:
    """Bring Chromium to the front and stretch the window (avoids tiny/minimised UI)."""
    try:
        await page.set_viewport_size(VIEWPORT)
    except Exception:
        pass
    try:
        cdp = await page.context.new_cdp_session(page)
        win = await cdp.send("Browser.getWindowForTarget")
        window_id = win.get("windowId")
        if window_id is not None:
            await cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": window_id,
                    "bounds": {
                        "windowState": "normal",
                        "width": VIEWPORT["width"],
                        "height": VIEWPORT["height"],
                        "left": 40,
                        "top": 40,
                    },
                },
            )
        await cdp.detach()
    except Exception as exc:
        logger.debug("window maximize skipped: %s", exc)
    try:
        await page.bring_to_front()
    except Exception:
        pass


class BrowserManager:
    def __init__(self, headless: bool = False) -> None:
        self.headless = headless
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> "BrowserManager":
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=[
                "--start-maximized",
                f"--window-size={VIEWPORT['width']},{VIEWPORT['height']}",
            ],
        )
        self._context = await self._browser.new_context(viewport=dict(VIEWPORT))
        self._page = await self._context.new_page()
        await _maximize_page(self._page)
        return self

    async def __aexit__(self, *_) -> None:
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    @property
    def page(self) -> Page:
        assert self._page is not None
        return self._page

    async def export_session_state(self) -> dict[str, Any]:
        assert self._context is not None
        return await self._context.storage_state()

    async def load_session_state(self, storage_state: dict[str, Any]) -> None:
        """Open a new context with saved cookies (for future phases)."""
        assert self._browser is not None
        if self._context:
            await self._context.close()
        self._context = await self._browser.new_context(
            storage_state=storage_state,
            viewport=dict(VIEWPORT),
        )
        if self._page:
            await self._page.close()
        self._page = await self._context.new_page()
        await _maximize_page(self._page)
