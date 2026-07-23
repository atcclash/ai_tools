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


_ANTIBOT_MARKERS = [
    "just a moment", "enable javascript", "checking your browser", "cloudflare",
    "performing security verification", "recaptcha", "px-captcha",
    "are you a robot", "are you human", "access denied", "continue shopping",
    "request could not be satisfied", "verify you are a human",
    "unusual traffic", "local_rate_limited",
]

# Substrings that mean we got an interstitial/challenge instead of the product page.
_CHALLENGE_MARKERS = [
    "just a moment", "performing security verification", "checking your browser",
    "continue shopping", "enable javascript and cookies",
]


def debug_snapshot(html: str, settings: dict) -> str:
    """A compact one-line diagnosis of a page: title, size, anti-bot flag, which
    stock markers matched, and the start of the visible text. Debug mode only."""
    tree = HTMLParser(html)
    title_node = tree.css_first("title")
    title = title_node.text(strip=True) if title_node else ""
    text = extract_text(html)
    low = text.lower()
    antibot = [m for m in _ANTIBOT_MARKERS if m in low]
    oos = [m for m in settings.get("out_of_stock_markers", []) if m.lower() in low]
    ins = [m for m in settings.get("in_stock_markers", []) if m.lower() in low]
    snippet = re.sub(r"\s+", " ", text)[:240]
    return (
        f"title={title!r} textlen={len(text)} "
        f"antibot={antibot or '-'} oos={oos or '-'} ins={ins or '-'} :: {snippet}"
    )


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


def parse_shopify_product(product: dict) -> dict:
    """Turn a Shopify `/products/<handle>.js` payload into analyze-style fields."""
    variants = product.get("variants", []) or []
    in_stock = product.get("available")
    if in_stock is None:
        in_stock = any(v.get("available") for v in variants)

    # Shopify prices are integer minor units (pence).
    prices = [v["price"] for v in variants if isinstance(v.get("price"), (int, float))]
    cents = min(prices) if prices else product.get("price")
    price = round(cents / 100, 2) if isinstance(cents, (int, float)) else None

    return {
        "in_stock": bool(in_stock),
        "price": price,
        "price_text": f"£{price:.2f}" if price is not None else None,
        "dispatch": None,
        "debug": f"shopify title={product.get('title')!r} available={in_stock} price={price}",
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

    def fetch_shopify(self, url: str) -> dict:
        """Read a Shopify product's structured JSON (`/products/<handle>.js`).

        Bypasses the HTML page (and its bot-wall/rate-limit) and returns exact
        stock + price from the store's own data. Returns analyze-style fields.
        """
        import httpx

        endpoint = url.split("?")[0].rstrip("/") + ".js"
        timeout = self.settings.get("page_timeout_ms", 30000) / 1000
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-GB,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
        }
        resp = httpx.get(endpoint, headers=headers, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return parse_shopify_product(resp.json())

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
            # Let client-rendered stock/price widgets settle: wait for the network
            # to go quiet (capped), then a short fixed pause as a backstop.
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:  # noqa: BLE001 — networkidle is best-effort
                pass
            page.wait_for_timeout(2500)
            content = page.content()
            return self._clear_interstitial(page, content)
        finally:
            context.close()

    @staticmethod
    def _clear_interstitial(page, content: str) -> str:
        """If the page is a Cloudflare challenge or Amazon 'Continue shopping'
        interstitial, give it a couple of chances to resolve (auto-pass or a
        button click) and re-read. Best-effort — walls that don't clear stay
        UNKNOWN rather than producing a wrong answer."""
        for _ in range(2):
            low = content.lower()
            if not any(m in low for m in _CHALLENGE_MARKERS):
                return content
            # Amazon's interstitial has a "Continue shopping" button — try it.
            try:
                btn = page.query_selector(
                    "input[type=submit], button:has-text('Continue'), a:has-text('Continue')"
                )
                if btn:
                    btn.click(timeout=4000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(6000)  # let a non-interactive challenge auto-clear
            try:
                page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:  # noqa: BLE001
                pass
            content = page.content()
        return content
