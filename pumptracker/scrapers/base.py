"""Fetching + page analysis shared by all scrapers.

The analysis functions (``extract_text``, ``detect_stock``, ``extract_price``,
``extract_dispatch``, ``analyze``) are pure functions over HTML, so they can be
unit-tested against saved fixtures without any network access. ``Fetcher`` wraps
the two ways we pull a page: a real headless browser (default) and a plain HTTP
GET for the rare clean-static page.
"""

from __future__ import annotations

import os
import random
import re
from typing import Optional

from selectolax.parser import HTMLParser

# A few realistic desktop UAs; we pick one per run so requests don't all look identical.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

_PRICE_RE = re.compile(r"£\s?([0-9]{1,4}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)")


def _strip_noise(tree: HTMLParser) -> None:
    for tag in ("script", "style", "noscript", "template", "svg"):
        for node in tree.css(tag):
            node.decompose()


def extract_text(html: str, separator: str = " ") -> str:
    """Visible text of a page, scripts/styles removed."""
    tree = HTMLParser(html)
    _strip_noise(tree)
    body = tree.body or tree
    return body.text(separator=separator, strip=True)


def detect_stock(text_lower: str, settings: dict) -> Optional[bool]:
    """Decide stock state from page text.

    Returns True (in stock), False (out of stock), or None (couldn't tell).
    Out-of-stock markers take precedence: many pages keep an "add to basket"
    button in the DOM even when the item is sold out.
    """
    for marker in settings.get("out_of_stock_markers", []):
        if marker.lower() in text_lower:
            return False
    for marker in settings.get("in_stock_markers", []):
        if marker.lower() in text_lower:
            return True
    return None


def extract_price(
    html: str,
    text: str,
    settings: dict,
    price_selector: Optional[str] = None,
) -> tuple[Optional[float], Optional[str]]:
    """Return (numeric_gbp, raw_text). Uses a CSS selector when given, else regex."""
    candidates: list[str] = []

    if price_selector:
        tree = HTMLParser(html)
        node = tree.css_first(price_selector)
        if node:
            candidates.append(node.text(strip=True))

    # Fall back to scanning visible text for £ amounts.
    search_space = " ".join(candidates) if candidates else text
    lo = settings.get("price_min_plausible", 0)
    hi = settings.get("price_max_plausible", 100000)

    for raw in _PRICE_RE.findall(search_space):
        value = float(raw.replace(",", ""))
        if lo <= value <= hi:
            return value, f"£{raw}"
    return None, None


def extract_dispatch(text_newlines: str, settings: dict) -> Optional[str]:
    """Best-effort: first short line mentioning dispatch/delivery."""
    keywords = [k.lower() for k in settings.get("dispatch_keywords", [])]
    if not keywords:
        return None
    for line in text_newlines.splitlines():
        clean = line.strip()
        low = clean.lower()
        if 3 < len(clean) <= 120 and any(k in low for k in keywords):
            return clean
    return None


def analyze(html: str, settings: dict, price_selector: Optional[str] = None) -> dict:
    """Turn raw HTML into the fields of a ProductResult (stock/price/dispatch)."""
    text = extract_text(html, separator=" ")
    text_nl = extract_text(html, separator="\n")
    in_stock = detect_stock(text.lower(), settings)
    price, price_text = extract_price(html, text, settings, price_selector)
    dispatch = extract_dispatch(text_nl, settings)
    return {
        "in_stock": in_stock,
        "price": price,
        "price_text": price_text,
        "dispatch": dispatch,
    }


class Fetcher:
    """Fetches pages, reusing one browser across all targets in a run."""

    def __init__(self, settings: dict):
        self.settings = settings
        self.user_agent = random.choice(USER_AGENTS)
        self._pw = None
        self._browser = None

    # -- browser lifecycle (lazy: only started if a playwright target is hit) --
    def _ensure_browser(self):
        if self._browser is not None:
            return
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        launch_kwargs = {"headless": True}
        # Optional: point at an already-installed Chromium (e.g. a preinstalled
        # browser or a version that doesn't match this Playwright build).
        exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
        if exe:
            launch_kwargs["executable_path"] = exe
        self._browser = self._pw.chromium.launch(**launch_kwargs)

    def close(self) -> None:
        try:
            if self._browser is not None:
                self._browser.close()
        finally:
            if self._pw is not None:
                self._pw.stop()
            self._browser = None
            self._pw = None

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- fetch methods ---------------------------------------------------------
    def fetch(self, url: str, method: str = "playwright") -> str:
        if method == "httpx":
            return self._fetch_httpx(url)
        return self._fetch_playwright(url)

    def _fetch_httpx(self, url: str) -> str:
        import httpx

        timeout = self.settings.get("page_timeout_ms", 30000) / 1000
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def _fetch_playwright(self, url: str) -> str:
        self._ensure_browser()
        timeout = self.settings.get("page_timeout_ms", 30000)
        context = self._browser.new_context(
            user_agent=self.user_agent,
            locale="en-GB",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={"Accept-Language": "en-GB,en;q=0.9"},
        )
        # Skip images/media/fonts — we only need the DOM text, and it's much faster.
        context.route(
            re.compile(r"\.(png|jpg|jpeg|gif|webp|svg|woff2?|ttf|mp4|avif)(\?.*)?$", re.I),
            lambda route: route.abort(),
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            # Give client-rendered stock/price widgets a moment to populate.
            page.wait_for_timeout(2500)
            return page.content()
        finally:
            context.close()
