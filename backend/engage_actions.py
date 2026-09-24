"""Locate latest LinkedIn post and like / comment / repost.

Selectors and flow adapted from proven open-source bots:
  - joeygoesgrey/Linkedln-Automation-Framework (ui_selectors / engage_flow)
  - PacemakerX/LinkedIntel (core/action_engine.py — JS click on social bar)
  - SelmiAbderrahim/automate-linkedin (feed card Like aria-label patterns)

Profile feeds are engaged on the card that owns the social action bar.
Company posts stay on the Posts tab. The newest SDUI card already has
Like, Comment, and Repost; those buttons are scrolled into view and clicked.
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Locator, Page

from engagement_store import canonicalize_post_urn

COMMENT_TEXT = "Insightful"
_ACTIVITY_URN_RE = re.compile(
    r"(urn:li:(?:activity|ugcPost|share):\d+)", re.I
)

# —— Selectors from LAF EngageSelectors / FeedActionSelectors ——
LIKE_SELECTORS = [
    'button[aria-label="Reaction button state: no reaction"]',
    "button.react-button__trigger",
    "button[aria-label='React Like']",
    "button[aria-label*='Like'][aria-label*='post' i]",
    "button[aria-label*='Like' i][aria-pressed='false']",
    "button:has(span:text-is('Like'))",
]
COMMENT_SELECTORS = [
    "button.comment-button",
    "button[aria-label='Comment']",
    "button[aria-label*='Comment' i]",
    "button:has(span:text-is('Comment'))",
    "button[data-control-name='comment']",
]
EDITOR_SELECTORS = [
    "div.ql-editor[contenteditable='true']",
    "div[contenteditable='true'][role='textbox']",
    "form.comments-comment-box__form div[contenteditable='true']",
    "div[contenteditable='true'].ql-editor",
]
SUBMIT_SELECTORS = [
    "button.comments-comment-box__submit-button",
    "button.comments-comment-box__submit-button--cr",
    "button[data-control-name='submit_comment']",
    "button[aria-label*='Post comment' i]",
    "button:has(span:text-is('Post'))",
]
REPOST_SELECTORS = [
    "button.social-reshare-button",
    "button[data-finite-scroll-hotkey='r']",
    "button[aria-label*='Repost' i]",
    "button:has(span:text-is('Repost'))",
]
ACTION_BAR_SEL = (
    "div.feed-shared-social-action-bar, "
    "div.feed-shared-social-actions, "
    "div.update-v2-social-activity"
)


@dataclass
class LatestPost:
    post_urn: str
    post_url: str
    preview: str = ""
    card_index: int = 0
    feed_url: str = ""


@dataclass
class EngageResult:
    ok: bool
    outcome: str
    detail: str = ""
    liked: bool = False
    commented: bool = False
    reposted: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


async def _pause(lo: float = 0.4, hi: float = 1.1) -> None:
    await asyncio.sleep(random.uniform(lo, hi))


async def _js_click(page: Page, locator: Locator) -> bool:
    """LinkedIntel-style: scroll + execute_script click (more reliable than Playwright click)."""
    try:
        handle = await locator.element_handle(timeout=2500)
        if not handle:
            return False
        await page.evaluate(
            """(el) => {
              el.scrollIntoView({behavior: 'smooth', block: 'center'});
              window.scrollBy(0, -80);
            }""",
            handle,
        )
        await _pause(0.25, 0.5)
        await page.evaluate("(el) => el.click()", handle)
        return True
    except Exception:
        try:
            await locator.click(timeout=3000, force=True)
            return True
        except Exception:
            return False


def feed_url_candidates(source_url: str) -> list[str]:
    """One primary URL, plus a single fallback. Never walk the full post history."""
    raw = (source_url or "").strip()
    if raw.startswith("/"):
        raw = "https://www.linkedin.com" + raw
    path = (urlparse(raw).path or "").rstrip("/")
    urls: list[str] = []

    if "/company/" in path or "/school/" in path:
        m = re.search(r"/(?:company|school)/([^/]+)", path, re.I)
        slug = m.group(1) if m else path.split("/")[-1]
        base = f"https://www.linkedin.com/company/{slug}"
        # Same URL the outreach activity scraper uses for a company page.
        urls.extend(
            [
                f"{base}/posts/",
                f"{base}/posts/?feedView=all",
            ]
        )
    elif "/in/" in path:
        root = path.split("/recent-activity")[0].rstrip("/")
        urls.append(f"https://www.linkedin.com{root}/recent-activity/all/")
    else:
        urls.append(raw if raw.endswith("/") else raw + "/")

    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def feed_url_for_source(source_url: str) -> str:
    cands = feed_url_candidates(source_url)
    return cands[0] if cands else source_url


# Company posts (abhishekgoyal scraper + LinkedIn org feed):
#   URL  /company/{slug}/posts/?feedView=all
#   card div.fie-impression-container  or  #organization-feed .feed-shared-update-v2
#   like button[aria-label*="Like"] inside .feed-shared-social-action-bar
#        ("Like Hexawealth's post", not the exact word Like)
_MARK_COMPANY_POST_JS = """() => {
  document.querySelectorAll('[data-hw-engage]').forEach((el) => el.removeAttribute('data-hw-engage'));
  const list = document.querySelectorAll(
    '#organization-feed .feed-shared-update-v2, #organization-feed .fie-impression-container, div.fie-impression-container, div.feed-shared-update-v2[data-urn*="activity"]'
  );
  const card = [...list].find((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 260 && r.left < window.innerWidth * 0.75 && r.height > 40;
  });
  if (!card) return null;
  card.setAttribute('data-hw-engage', '1');
  const bar = card.querySelector('.feed-shared-social-action-bar, .feed-shared-social-actions');
  (bar || card).scrollIntoView({ block: 'center' });
  const blob = (card.getAttribute('data-urn') || '') + ' ' + (card.innerHTML || '').slice(0, 20000);
  const m = blob.match(/urn:li:activity:(\\d{8,})/);
  return {
    urn: m ? ('urn:li:activity:' + m[1]) : '',
    text: (card.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120),
  };
}"""

_LOCK_COMPANY_LIKE_JS = """() => {
  const scoped = document.querySelector(
    '[data-hw-engage="1"] .feed-shared-social-action-bar button[aria-label*="Like" i], [data-hw-engage="1"] button[aria-label*="Like" i]'
  );
  const nodes = scoped
    ? [scoped]
    : [...document.querySelectorAll('main button, main [role="button"], button, [role="button"]')];
  const like = nodes.find((b) => {
    const r = b.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) return false;
    if (r.left > window.innerWidth * 0.70) return false;
    const aria = (b.getAttribute('aria-label') || '').trim();
    const text = (b.innerText || '').trim();
    if (/comment|unlike|follow|message/i.test(aria + ' ' + text)) return false;
    return /like/i.test(aria) || /^like$/i.test(text) || /open reactions menu/i.test(aria);
  });
  if (!like) return false;
  let card = like;
  for (let i = 0; i < 14 && card.parentElement; i++) {
    const pr = card.parentElement.getBoundingClientRect();
    if (pr.width > 320 && pr.height > 80 && pr.left < window.innerWidth * 0.7) card = card.parentElement;
    else break;
  }
  document.querySelectorAll('[data-hw-engage]').forEach((el) => el.removeAttribute('data-hw-engage'));
  card.setAttribute('data-hw-engage', '1');
  like.scrollIntoView({ block: 'center' });
  return true;
}"""

_SCROLL_COMPANY_BAR_JS = """() => {
  const dy = 700;
  const targets = new Set();
  let node = document.querySelector('[data-hw-engage="1"]');
  while (node) {
    targets.add(node);
    node = node.parentElement;
  }
  [document.scrollingElement, document.documentElement, document.body,
   document.querySelector('main'),
   document.querySelector('.scaffold-layout__main'),
   document.querySelector('.scaffold-layout__list-container'),
   document.querySelector('.org-organization-page__container')
  ].forEach((el) => { if (el) targets.add(el); });
  document.querySelectorAll('div').forEach((el) => {
    if (el.scrollHeight > el.clientHeight + 80) targets.add(el);
  });
  let moved = 0;
  targets.forEach((el) => {
    try {
      const before = el.scrollTop || 0;
      el.scrollTop = before + dy;
      if ((el.scrollTop || 0) > before + 5) moved += 1;
    } catch (e) {}
  });
  const y = window.scrollY || 0;
  window.scrollTo(0, y + dy);
  if ((window.scrollY || 0) > y + 5) moved += 1;
  return moved;
}"""

_READ_COMPANY_POST_JS = """() => {
  const card = document.querySelector('[data-hw-engage="1"]');
  if (!card) return null;
  const blob = (card.innerHTML || '').slice(0, 40000);
  const m = blob.match(/(?:urn:li:(?:activity|ugcPost|share):|activity[:-])(\\d{8,})/i);
  const urn = m ? ('urn:li:activity:' + m[1]) : ('company-post:' + location.pathname);
  return {
    index: 0,
    urn,
    href: m ? ('https://www.linkedin.com/feed/update/urn:li:activity:' + m[1] + '/') : location.href,
    text: (card.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120),
  };
}"""


# Company Posts tab (SDUI). The action bar is already on the card.
# There is no activity URN, so the inner componentkey is the post id.
_MARK_SDUI_COMPANY_POST_JS = """() => {
  const list = document.querySelector('[data-testid^="organizationFeed"]');
  if (!list) return null;
  const ageOf = (text) => {
    const m = (text || '').slice(0, 800).match(/(\\d+)\\s*(mo|w|d|h)\\b/i);
    if (!m) return 1e9;
    const n = parseInt(m[1], 10);
    const unit = m[2].toLowerCase();
    if (unit === 'h') return n;
    if (unit === 'd') return n * 24;
    if (unit === 'w') return n * 168;
    return n * 720;
  };
  const pickKey = (item) => {
    const nodes = [item, ...item.querySelectorAll('[componentkey]')];
    for (const node of nodes) {
      if (node.tagName === 'BUTTON' || node.tagName === 'A') continue;
      const key = node.getAttribute('componentkey') || '';
      if (key.length < 16) continue;
      if (/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(key)) continue;
      if (/^(update-card|expanded|auto-component)/i.test(key)) continue;
      if (/FeedType/i.test(key)) continue;
      return key;
    }
    return '';
  };
  document.querySelectorAll('[data-hw-engage]').forEach((el) => el.removeAttribute('data-hw-engage'));
  const items = [...list.querySelectorAll('[role="listitem"]')];
  let best = null;
  let bestAge = 1e9;
  for (const item of items) {
    const comment = item.querySelector('button[aria-label="Comment"]');
    if (!comment) continue;
    const nested = item.querySelector('[role="listitem"] button[aria-label="Comment"]');
    if (nested && nested.closest('[role="listitem"]') !== item) continue;
    const age = ageOf(item.innerText || '');
    if (!best || age < bestAge) {
      best = item;
      bestAge = age;
    }
  }
  if (!best) return null;
  const key = pickKey(best);
  if (!key) return null;
  best.setAttribute('data-hw-engage', '1');
  const react = best.querySelector('button[aria-label^="Reaction button state"]')
    || best.querySelector('button[aria-label="Comment"]')
    || best.querySelector('button[aria-label="Repost"]');
  if (react) react.scrollIntoView({ behavior: 'instant', block: 'center' });
  return {
    index: 0,
    urn: 'sdui:' + key,
    href: location.href,
    text: (best.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 160),
  };
}"""


_REMARK_SDUI_JS = """(key) => {
  if (!key) return false;
  document.querySelectorAll('[data-hw-engage]').forEach((el) => el.removeAttribute('data-hw-engage'));
  const esc = (window.CSS && CSS.escape) ? CSS.escape(key) : String(key).replace(/"/g, '');
  const el = document.querySelector('[componentkey="' + esc + '"]');
  if (!el) return false;
  const item = el.closest('[role="listitem"]') || el;
  item.setAttribute('data-hw-engage', '1');
  const react = item.querySelector('button[aria-label^="Reaction button state"]')
    || item.querySelector('button[aria-label="Comment"]')
    || item.querySelector('button[aria-label="Repost"]');
  if (react) react.scrollIntoView({ behavior: 'instant', block: 'center' });
  return true;
}"""


async def _mark_latest_company_sdui(page: Page) -> dict | None:
    try:
        await page.wait_for_selector('[data-testid^="organizationFeed"]', timeout=12000)
    except Exception:
        pass
    for _ in range(3):
        hit = await page.evaluate(_MARK_SDUI_COMPANY_POST_JS)
        if hit and hit.get("urn"):
            await _pause(0.3, 0.6)
            return hit
        await page.mouse.wheel(0, 400)
        await _pause(0.5, 0.8)
    return None


# Topmost post only. Do not require a Like button to "find" the post —
# requiring it made us scroll the whole history without ever engaging.
_EXTRACT_POSTS_JS = """() => {
  const urnRe = /urn:li:(?:activity|ugcPost|share):\\d+/i;
  const nodes = document.querySelectorAll(
    'div.feed-shared-update-v2, div[data-urn*="urn:li:"], article'
  );
  const hits = [];
  nodes.forEach((node, index) => {
    const urnAttr = node.getAttribute('data-urn') || node.getAttribute('data-id') || '';
    const link = node.querySelector('a[href*="activity"], a[href*="/feed/update/"], a[href*="ugcPost"]');
    const href = link ? (link.href || '') : '';
    const blob = urnAttr + ' ' + href;
    const m = blob.match(urnRe);
    if (!m) return;
    const rect = node.getBoundingClientRect();
    if (rect.height < 120 || rect.width < 200) return;
    // Skip cards nested inside a larger card we already have
    if (node.parentElement && node.parentElement.closest('[data-urn], .feed-shared-update-v2')) {
      const parent = node.parentElement.closest('[data-urn], .feed-shared-update-v2');
      if (parent && parent !== node && urnRe.test(parent.getAttribute('data-urn') || '')) return;
    }
    const textEl = node.querySelector('.update-components-text, .feed-shared-update-v2__description, span.break-words');
    hits.push({
      index,
      urn: m[0],
      href: href || ('https://www.linkedin.com/feed/update/' + m[0] + '/'),
      text: ((textEl && textEl.innerText) || '').trim().slice(0, 120),
      top: rect.top + window.scrollY,
    });
  });
  hits.sort((a, b) => a.top - b.top);
  const seen = new Set();
  const out = [];
  for (const h of hits) {
    const key = h.urn.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(h);
    if (out.length >= 1) break;  // latest = topmost only
  }
  return out;
}"""


# Same card + link query as hexawealth_outreach activity_scraper._extract_posts.
_EXTRACT_COMPANY_POST_JS = """() => {
  document.querySelectorAll('[data-hw-click]').forEach((el) => el.removeAttribute('data-hw-click'));
  const vw = window.innerWidth || 1440;
  const companyTab = /\\/company\\/[^/]+\\/posts\\/?(\\?|#|$)/i;
  const cards = document.querySelectorAll(
    'div.feed-shared-update-v2, div.occludable-update, article, div.fie-impression-container'
  );
  for (const card of cards) {
    const r = card.getBoundingClientRect();
    if (r.width < 180 || r.left > vw * 0.75) continue;
    const link = card.querySelector(
      'a[href*="/feed/update/"], a[href*="activity:"], a[href*="activity-"], a[href*="/posts/"]'
    );
    let href = link ? (link.href || '') : '';
    if (companyTab.test(href)) href = '';
    const textEl = card.querySelector(
      '.feed-shared-update-v2__description, .update-components-text, span.break-words'
    );
    const text = ((textEl && textEl.innerText) || '').trim();
    const urnAttr = card.getAttribute('data-urn') || card.getAttribute('data-id') || '';
    if (!href && !urnAttr && text.length < 20) continue;
    if (link && href) link.setAttribute('data-hw-click', '1');
    return { href, urn: urnAttr, text: text.slice(0, 140) };
  }
  const links = [...document.querySelectorAll('a[href]')];
  for (const a of links) {
    const href = a.href || '';
    if (companyTab.test(href)) continue;
    if (!/\\/feed\\/update\\/|activity[:-]\\d{8,}|linkedin\\.com\\/posts\\//i.test(href)) continue;
    const r = a.getBoundingClientRect();
    if (r.left > vw * 0.75) continue;
    a.setAttribute('data-hw-click', '1');
    return { href, urn: '', text: (a.innerText || '').trim().slice(0, 140) };
  }
  return null;
}"""


def _company_list_url(url: str) -> bool:
    return bool(re.search(r"/company/[^/]+/posts/?(\?|$)", url or "", re.I))


def _activity_id_from_url(url: str) -> str:
    m = re.search(r"activity[:-](\d{8,})", url or "", re.I)
    return m.group(1) if m else ""


def _post_open_url(href: str, urn: str) -> str:
    """Permalink outreach uses: the card href, or /feed/update/{urn}/."""
    m = _ACTIVITY_URN_RE.search(urn or "") or _ACTIVITY_URN_RE.search(href or "")
    if m:
        return f"https://www.linkedin.com/feed/update/{canonicalize_post_urn(m.group(1))}/"
    bare = _activity_id_from_url(href) or _activity_id_from_url(urn)
    if bare and href and "/posts/" in href and "linkedin.com" in href:
        return href.split("?")[0]
    if bare:
        return f"https://www.linkedin.com/feed/update/urn:li:activity:{bare}/"
    return (href or "").split("?")[0]


async def _jittered_click(page: Page, loc: Locator) -> bool:
    """Same pointer click outreach uses in jittered_click."""
    try:
        await loc.wait_for(state="visible", timeout=8000)
        box = await loc.bounding_box()
        if box:
            x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
            await page.mouse.move(x, y, steps=random.randint(8, 16))
            await _pause(0.05, 0.25)
        await loc.click(timeout=5000)
        return True
    except Exception:
        return False


async def _click_open_latest_company_post(page: Page) -> dict | None:
    """Find the latest company card the way activity_scraper does, click its
    link, and open that post URL if the click stays on the list."""
    raw = None
    for i in range(5):
        try:
            raw = await page.evaluate(_EXTRACT_COMPANY_POST_JS)
        except Exception:
            raw = None
        if raw and (raw.get("href") or raw.get("urn")):
            break
        try:
            await page.evaluate("window.scrollBy(0, Math.max(700, window.innerHeight * 0.8))")
        except Exception:
            pass
        await _pause(1.0, 1.3)
        if i == 3:
            try:
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass

    if not raw:
        return None

    href = (raw.get("href") or "").strip()
    urn = (raw.get("urn") or "").strip()
    preview = (raw.get("text") or "").strip()
    open_url = _post_open_url(href, urn)
    if not open_url:
        return None

    before = page.url
    loc = page.locator("[data-hw-click='1']").first
    try:
        if await loc.count() > 0:
            await loc.scroll_into_view_if_needed(timeout=3000)
            await _jittered_click(page, loc)
            try:
                await page.wait_for_url(
                    lambda u: u != before and not _company_list_url(u),
                    timeout=6000,
                )
            except Exception:
                pass
    except Exception:
        pass

    if _company_list_url(page.url or "") or page.url == before:
        try:
            await page.goto(open_url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            return None

    await _pause(1.4, 2.0)
    found = (
        _ACTIVITY_URN_RE.search(page.url or "")
        or _ACTIVITY_URN_RE.search(open_url)
        or _ACTIVITY_URN_RE.search(urn)
        or _ACTIVITY_URN_RE.search(href)
    )
    if found:
        post_urn = canonicalize_post_urn(found.group(1))
    else:
        activity_id = (
            _activity_id_from_url(page.url or "")
            or _activity_id_from_url(open_url)
            or _activity_id_from_url(urn)
        )
        if not activity_id:
            try:
                activity_id = await page.evaluate(
                    """() => {
                      const html = (document.body && document.body.innerHTML || '').slice(0, 200000);
                      const m = html.match(/urn:li:(?:activity|ugcPost|share):(\\d{8,})/)
                        || html.match(/activity-(\\d{8,})/);
                      return m ? m[1] : '';
                    }"""
                )
            except Exception:
                activity_id = ""
        if not activity_id:
            return None
        post_urn = f"urn:li:activity:{activity_id}"

    try:
        await page.evaluate(
            """() => {
              const root = document.querySelector('[componentkey$="FeedType_FEED_DETAIL"]')
                || document.querySelector('main')
                || document.body;
              document.querySelectorAll('[data-hw-engage]').forEach((el) => el.removeAttribute('data-hw-engage'));
              root.setAttribute('data-hw-engage', '1');
            }"""
        )
    except Exception:
        pass

    for _ in range(10):
        try:
            if await page.evaluate(_LOCK_COMPANY_LIKE_JS):
                break
        except Exception:
            pass
        try:
            await page.keyboard.press("End")
        except Exception:
            pass
        try:
            await page.mouse.move(640, 500)
            await page.mouse.wheel(0, 1400)
        except Exception:
            pass
        try:
            await page.evaluate(_SCROLL_COMPANY_BAR_JS)
        except Exception:
            pass
        await _pause(0.45, 0.7)

    return {
        "index": 0,
        "urn": post_urn,
        "href": page.url,
        "text": preview,
    }


async def _load_feed(page: Page, url: str) -> list[dict]:
    """Open the feed and stop at the first (latest) post. Never deep-scroll history."""
    try:
        await page.set_viewport_size({"width": 1440, "height": 960})
    except Exception:
        pass
    try:
        await page.bring_to_front()
    except Exception:
        pass

    await page.goto(url, wait_until="domcontentloaded")
    await _pause(2.0, 2.8)
    company = "/company/" in (url or "")

    for sel in (
        'button[aria-label="Dismiss"]',
        'button.artdeco-modal__dismiss',
        'button:has-text("Dismiss")',
        'button:has-text("Not now")',
    ):
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible(timeout=400):
                await _js_click(page, btn)
                await _pause(0.3, 0.5)
                break
        except Exception:
            pass

    if company:
        opened = await _mark_latest_company_sdui(page)
        if not opened:
            return []
        return [opened]

    extract_js = _EXTRACT_POSTS_JS

    # At most two short nudges so the first cards mount. Stop the moment one exists.
    found: list[dict] = []
    for _ in range(3):
        found = await page.evaluate(extract_js)
        if found:
            break
        try:
            await page.evaluate("window.scrollBy(0, Math.min(700, window.innerHeight * 0.6))")
        except Exception:
            pass
        await _pause(0.9, 1.3)

    if found:
        try:
            await page.evaluate(
                """(urn) => {
                  const marked = document.querySelector('[data-hw-engage="1"]');
                  const el = marked
                    || document.querySelector('[data-urn="' + urn + '"]')
                    || document.querySelector('[data-urn*="' + String(urn).split(':').pop() + '"]');
                  if (el) el.scrollIntoView({behavior: 'instant', block: 'center'});
                }""",
                found[0].get("urn") or "",
            )
            await _pause(0.4, 0.7)
        except Exception:
            pass
    return found or []


async def find_latest_post(page: Page, source_url: str) -> LatestPost | None:
    for url in feed_url_candidates(source_url):
        try:
            raw_list = await _load_feed(page, url)
        except Exception:
            continue
        if not raw_list:
            continue
        raw = raw_list[0]
        href = (raw.get("href") or "").strip()
        urn_raw = (raw.get("urn") or "").strip()
        if urn_raw.lower().startswith("sdui:"):
            urn = canonicalize_post_urn(urn_raw)
            href = href or page.url
        else:
            m = _ACTIVITY_URN_RE.search(urn_raw) or _ACTIVITY_URN_RE.search(href)
            if m:
                urn = canonicalize_post_urn(m.group(1))
            else:
                bare = re.search(r"activity[:-](\d{8,})", f"{urn_raw} {href}", re.I)
                if not bare:
                    continue
                urn = f"urn:li:activity:{bare.group(1)}"
            if not href:
                href = f"https://www.linkedin.com/feed/update/{urn}/"
        return LatestPost(
            post_urn=urn,
            post_url=href,
            preview=raw.get("text") or "",
            card_index=int(raw.get("index") or 0),
            feed_url=url,
        )
    return None


async def _card_for_post(page: Page, post: LatestPost) -> Locator | None:
    """Find the already-loaded card. Do not reload or scroll the history again."""
    urn = post.post_urn
    if urn.lower().startswith("sdui:"):
        key = urn.split(":", 1)[1]
        marked = page.locator("[data-hw-engage='1']").first
        try:
            if await marked.count() == 0:
                await page.evaluate(_REMARK_SDUI_JS, key)
                marked = page.locator("[data-hw-engage='1']").first
            if await marked.count() > 0:
                return marked
        except Exception:
            return None
        return None
    digit = urn.split(":")[-1]
    marked = page.locator("[data-hw-engage='1']").first
    try:
        if await marked.count() > 0:
            try:
                if not await page.evaluate(_LOCK_COMPANY_LIKE_JS):
                    await page.evaluate(_SCROLL_COMPANY_BAR_JS)
                    await _pause(0.4, 0.7)
            except Exception:
                pass
            return marked
    except Exception:
        pass

    candidates = [
        page.locator(f'div.feed-shared-update-v2[data-urn="{urn}"]'),
        page.locator(f'[data-urn="{urn}"]'),
        page.locator(f'div.feed-shared-update-v2[data-urn*="{digit}"]'),
        page.locator(f'[data-urn*="{digit}"]'),
    ]
    for loc in candidates:
        try:
            n = await loc.count()
        except Exception:
            continue
        # Prefer the outermost / largest match
        best = None
        best_box = 0
        for i in range(min(n, 6)):
            card = loc.nth(i)
            try:
                box = await card.bounding_box()
            except Exception:
                box = None
            area = (box["width"] * box["height"]) if box else 0
            if area >= best_box:
                best_box = area
                best = card
        if best is not None and best_box > 8000:
            try:
                handle = await best.element_handle()
                if handle:
                    await page.evaluate(
                        "(el) => el.scrollIntoView({behavior: 'instant', block: 'center'})",
                        handle,
                    )
                await _pause(0.3, 0.6)
            except Exception:
                pass
            return best
    return None


async def _first_in(card: Locator, selectors: list[str]) -> Locator | None:
    bar = card.locator(ACTION_BAR_SEL).first
    roots = [bar, card]
    for root in roots:
        for sel in selectors:
            loc = root.locator(sel)
            try:
                n = await loc.count()
            except Exception:
                continue
            for i in range(min(n, 6)):
                item = loc.nth(i)
                try:
                    if await item.is_visible(timeout=400):
                        return item
                except Exception:
                    continue
    return None


async def _do_like(page: Page, card: Locator) -> tuple[bool, str]:
    try:
        await card.hover(timeout=1500)
        await _pause(0.3, 0.5)
    except Exception:
        pass
    handle = await card.element_handle()
    if not handle:
        return False, "Like button not found"
    clicked = await page.evaluate(
        """(card) => {
          const buttons = [...card.querySelectorAll('button, [role="button"]')];
          const reaction = buttons.find((b) =>
            /^reaction button state:/i.test(b.getAttribute('aria-label') || '')
          );
          if (reaction) {
            const aria = (reaction.getAttribute('aria-label') || '').trim();
            if (/no reaction/i.test(aria)) {
              reaction.scrollIntoView({block: 'center'});
              reaction.click();
              return 'liked';
            }
            return 'already';
          }
          const already = buttons.find((b) => {
            const aria = (b.getAttribute('aria-label') || '').trim();
            return b.getAttribute('aria-pressed') === 'true' && /^like$/i.test(aria);
          });
          if (already) return 'already';
          const like = buttons.find((b) => {
            const aria = (b.getAttribute('aria-label') || '').trim();
            const text = (b.innerText || '').trim();
            if (/^unlike/i.test(aria)) return false;
            if (/comment/i.test(aria)) return false;
            if (b.getAttribute('aria-pressed') === 'true' && /^like\\b/i.test(aria)) return false;
            return /like/i.test(aria)
              || /^like$/i.test(text)
              || /^react like$/i.test(aria)
              || /^reaction button state:.*like/i.test(aria);
          });
          if (like) {
            if (like.getAttribute('aria-pressed') === 'true') return 'already';
            like.click();
            return 'liked';
          }
          const menu = buttons.find((b) => /open reactions menu/i.test(b.getAttribute('aria-label') || ''));
          if (menu) {
            menu.click();
            return 'menu';
          }
          const legacy = card.querySelector('button.react-button__trigger');
          if (legacy) { legacy.click(); return 'liked'; }
          return 'missing';
        }""",
        handle,
    )
    await _pause(0.5, 0.9)
    if clicked == "menu":
        like = page.locator('button[aria-label="Like"], button[aria-label^="Like "]').first
        try:
            if await like.count() > 0 and await like.is_visible(timeout=1500):
                await _js_click(page, like)
                await _pause(0.4, 0.7)
                return True, "liked"
        except Exception:
            return False, "Like button not found"
    if clicked == "already":
        return True, "already liked"
    if clicked == "liked":
        return True, "liked"

    # Outreach like_or_brand: role name Like, then aria-label, on the opened post.
    like = page.get_by_role("button", name="Like")
    try:
        if await like.count() == 0:
            like = page.locator('button[aria-label*="Like"]').first
        if await like.count() > 0:
            await like.first.scroll_into_view_if_needed(timeout=3000)
            if await _jittered_click(page, like.first):
                return True, "liked"
    except Exception:
        pass
    return False, "Like button not found"


async def _do_comment(
    page: Page, card: Locator, text: str = COMMENT_TEXT
) -> tuple[bool, str]:
    editor = None
    for sel in EDITOR_SELECTORS:
        loc = card.locator(sel).first
        try:
            if await loc.count() > 0:
                handle = await loc.element_handle()
                if handle:
                    await page.evaluate(
                        "(el) => el.scrollIntoView({block: 'center'})", handle
                    )
                if await loc.is_visible(timeout=600):
                    editor = loc
                    break
        except Exception:
            continue

    # Company cards already mount the editor. Clicking Comment again closes it.
    if editor is None:
        comment_btn = await _first_in(card, COMMENT_SELECTORS)
        opened = False
        if comment_btn is not None:
            opened = await _js_click(page, comment_btn)
        if not opened:
            handle = await card.element_handle()
            if handle:
                opened = bool(
                    await page.evaluate(
                        """(card) => {
                          const b = [...card.querySelectorAll('button')].find(el =>
                            /^comment$/i.test((el.getAttribute('aria-label') || '').trim())
                          );
                          if (!b) return false;
                          b.scrollIntoView({block: 'center'});
                          b.click();
                          return true;
                        }""",
                        handle,
                    )
                )
        await _pause(0.8, 1.3)

    if editor is None:
        for _ in range(8):
            for sel in EDITOR_SELECTORS:
                loc = card.locator(sel).first
                try:
                    if await loc.count() > 0 and await loc.is_visible(timeout=400):
                        editor = loc
                        break
                except Exception:
                    continue
            if editor is not None:
                break
            await _pause(0.35, 0.55)

    if editor is None:
        return False, "Comment editor not found"

    try:
        handle = await editor.element_handle()
        if handle:
            await page.evaluate("(el) => el.focus()", handle)
        await editor.click(timeout=2000)
        await _pause(0.2, 0.4)
        await page.keyboard.type(text, delay=random.randint(30, 70))
    except Exception:
        try:
            await editor.fill(text)
        except Exception as exc:
            return False, f"Failed to type comment: {exc}"

    typed = await page.evaluate(
        """() => {
          const box = document.querySelector(
            "div.tiptap.ProseMirror[contenteditable='true'], div[contenteditable='true'][role='textbox']"
          );
          return box ? (box.innerText || '').trim() : '';
        }"""
    )
    if text.lower() not in (typed or "").lower():
        await page.evaluate(
            """(comment) => {
              const box = document.querySelector(
                "div.tiptap.ProseMirror[contenteditable='true'], div[contenteditable='true'][role='textbox']"
              );
              if (!box) return;
              box.focus();
              document.execCommand('insertText', false, comment);
            }""",
            text,
        )
    await _pause(0.4, 0.7)

    # SDUI composer has no Post button until text is in. The social-bar
    # button is aria-label="Comment" — never click that one again.
    posted = await page.evaluate(
        """() => {
          const box = document.querySelector(
            "div.tiptap.ProseMirror[contenteditable='true'], div[contenteditable='true'][role='textbox']"
          );
          if (!box) return false;
          let root = box;
          for (let i = 0; i < 12 && root.parentElement; i++) {
            const parent = root.parentElement;
            if (parent.querySelector("button[aria-label^='Reaction button state']")) break;
            root = parent;
          }
          const btn = [...root.querySelectorAll('button')].find((el) => {
            if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
            const label = (el.getAttribute('aria-label') || '').trim();
            const words = (el.innerText || '').replace(/\\s+/g, ' ').trim();
            if (/reaction button state|emoji|gif|share photo|open control/i.test(label)) return false;
            return /^(post|comment|post comment)$/i.test(words) || /^(post|comment|post comment)$/i.test(label);
          });
          if (!btn) return false;
          btn.click();
          return true;
        }"""
    )
    if not posted:
        try:
            await editor.click(timeout=2000)
            await page.keyboard.press("Meta+Enter")
            await _pause(0.5, 0.8)
            await page.keyboard.press("Control+Enter")
        except Exception:
            return False, "Comment submit not found"
    await _pause(1.0, 1.6)
    still = await page.evaluate(
        """(comment) => {
          const box = document.querySelector(
            "div.tiptap.ProseMirror[contenteditable='true'], div[contenteditable='true'][role='textbox']"
          );
          if (!box) return false;
          return (box.innerText || '').toLowerCase().includes(comment.toLowerCase());
        }""",
        text,
    )
    if still:
        return False, "Comment did not submit"
    return True, "commented"


async def _do_repost(page: Page, card: Locator) -> tuple[bool, str]:
    """Open the Repost menu, then click **Repost instantly** (not 'with thoughts').

    LinkedIn's bar button only opens a menu; treating that click as success is a
    false positive. We must select the instant option from the dropdown.
    """
    repost = await _first_in(card, REPOST_SELECTORS)
    if repost is None:
        handle = await card.element_handle()
        if not handle:
            return False, "Repost button not found"
        found = await page.evaluate(
            """(card) => {
              const bar = card.querySelector(
                '.feed-shared-social-action-bar, .feed-shared-social-actions, .update-v2-social-activity'
              ) || card;
              const b = [...bar.querySelectorAll('button')].find(el => {
                const t = (el.getAttribute('aria-label') || el.innerText || '').toLowerCase();
                return t.includes('repost') || t.includes('reshare') || (el.className || '').includes('social-reshare');
              });
              if (b) { b.click(); return true; }
              return false;
            }""",
            handle,
        )
        if not found:
            return False, "Repost button not found"
    else:
        if not await _js_click(page, repost):
            return False, "Failed to click Repost"

    await _pause(0.7, 1.2)

    # Prefer explicit "Repost instantly" (current LinkedIn menu copy).
    instant_selectors = (
        '[role="menuitem"]:has-text("Repost instantly")',
        '[role="menu"] >> text=/Repost instantly/i',
        'div.artdeco-dropdown__content >> text=/Repost instantly/i',
        'div.social-reshare-button__share-dropdown-content >> text=/Repost instantly/i',
        'button:has-text("Repost instantly")',
        'div[role="button"]:has-text("Repost instantly")',
    )
    for sel in instant_selectors:
        opt = page.locator(sel).first
        try:
            if await opt.count() == 0:
                continue
            if not await opt.is_visible(timeout=1200):
                continue
            label = ((await opt.inner_text(timeout=500)) or "").lower()
            if "thought" in label:
                continue
            # Must be "Repost instantly" (or legacy exact "Repost" menu item).
            if "instant" not in label and not re.fullmatch(r"repost", label.strip()):
                continue
            if not await _js_click(page, opt):
                continue
            await _pause(0.9, 1.5)
            # Menu should close after a real instant repost.
            still_open = await page.evaluate(
                """() => {
                  const menus = [...document.querySelectorAll(
                    '[role="menu"], .artdeco-dropdown__content, .social-reshare-button__share-dropdown-content'
                  )];
                  return menus.some((m) => {
                    const t = (m.innerText || '');
                    return /repost instantly/i.test(t) || /repost with thoughts/i.test(t);
                  });
                }"""
            )
            if still_open:
                return False, "Repost menu still open after click"
            return True, "reposted instantly"
        except Exception:
            continue

    # Scoped JS: only options inside an open share/repost menu — never the bar button.
    instant = await page.evaluate(
        """() => {
          const menus = [...document.querySelectorAll(
            '[role="menu"], .artdeco-dropdown__content-inner, .artdeco-dropdown__content, .social-reshare-button__share-dropdown-content, .artdeco-dropdown__item'
          )].filter((m) => {
            const style = window.getComputedStyle(m);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const t = (m.innerText || '');
            return /repost/i.test(t);
          });
          const roots = menus.length ? menus : [];
          const candidates = [];
          for (const root of roots) {
            candidates.push(
              ...root.querySelectorAll(
                '[role="menuitem"], button, [role="button"], div[role="button"], li, span'
              )
            );
          }
          const normalize = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
          // 1) Prefer "Repost instantly"
          let item = candidates.find((el) => {
            const text = normalize(el.innerText);
            const label = normalize(el.getAttribute('aria-label'));
            return text.includes('repost instantly') || label.includes('repost instantly');
          });
          // 2) Legacy: menu item whose text is exactly "Repost" (not thoughts, not bar)
          if (!item) {
            item = candidates.find((el) => {
              const text = normalize(el.innerText);
              const label = normalize(el.getAttribute('aria-label'));
              if (text.includes('thought') || label.includes('thought')) return false;
              return text === 'repost' || label === 'repost';
            });
          }
          if (!item) return { ok: false, reason: 'instant_option_not_found' };
          item.click();
          return { ok: true, reason: 'clicked' };
        }"""
    )
    if isinstance(instant, dict) and instant.get("ok"):
        await _pause(0.9, 1.5)
        still_open = await page.evaluate(
            """() => {
              const menus = [...document.querySelectorAll(
                '[role="menu"], .artdeco-dropdown__content, .social-reshare-button__share-dropdown-content'
              )];
              return menus.some((m) => {
                const t = (m.innerText || '');
                return /repost instantly/i.test(t) || /repost with thoughts/i.test(t);
              });
            }"""
        )
        if still_open:
            return False, "Repost menu still open after click"
        return True, "reposted instantly"

    reason = (
        instant.get("reason")
        if isinstance(instant, dict)
        else "instant_option_not_found"
    )
    return False, f"Repost instantly not selected ({reason})"


async def engage_post(
    page: Page,
    post: LatestPost,
    *,
    actions: set[str] | None = None,
) -> EngageResult:
    """Run selected actions (like / comment / repost) on the post's action bar."""
    wanted = {a.strip().lower() for a in (actions or {"like", "comment", "repost"})}
    wanted &= {"like", "comment", "repost"}
    if not wanted:
        return EngageResult(False, "error", "No actions selected")

    card = await _card_for_post(page, post)
    if card is None and not post.post_urn.lower().startswith("sdui:"):
        main = page.locator(
            '[componentkey$="FeedType_FEED_DETAIL"], [data-testid="mainFeed"], main'
        ).first
        try:
            if await main.count() > 0:
                card = main
        except Exception:
            card = None
    if card is None:
        return EngageResult(
            False,
            "error",
            "Feed card with social action bar not found",
        )

    url = page.url or ""
    if any(x in url for x in ("checkpoint", "authwall", "/login")):
        return EngageResult(False, "challenged", "LinkedIn login wall")

    liked = commented = reposted = False
    details: list[str] = []
    failed = False

    if "like" in wanted:
        ok, detail = await _do_like(page, card)
        liked = ok
        details.append(f"like={detail}")
        if not ok:
            failed = True
        await _pause(0.8, 1.4)
        card = await _card_for_post(page, post) or card

    if "comment" in wanted:
        ok, detail = await _do_comment(page, card, COMMENT_TEXT)
        commented = ok
        details.append(f"comment={detail}")
        if not ok:
            failed = True
        await _pause(0.8, 1.4)
        card = await _card_for_post(page, post) or card

    if "repost" in wanted:
        ok, detail = await _do_repost(page, card)
        reposted = ok
        details.append(f"repost={detail}")
        if not ok:
            failed = True

    return EngageResult(
        not failed,
        "done" if not failed else "error",
        "; ".join(details),
        liked=liked,
        commented=commented,
        reposted=reposted,
        meta={"post_urn": post.post_urn, "post_url": post.post_url},
    )
