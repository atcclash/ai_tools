"""Config-driven scraper: fetch a target's page and produce a ProductResult.

One scraper handles every vendor. Per-vendor quirks live in config.yaml
(``method``, optional ``price_selector``). If a specific retailer ever needs
bespoke logic, add a module and dispatch to it from ``check_target``.
"""

from __future__ import annotations

from ..models import ProductResult
from . import base


def check_target(target: dict, settings: dict, fetcher: base.Fetcher) -> ProductResult:
    """Check a single target. Never raises — failures become error results."""
    result = ProductResult(
        target_id=target["id"],
        vendor=target["vendor"],
        product=target["product"],
        url=target["url"],
    )
    try:
        html = fetcher.fetch(target["url"], method=target.get("method", "playwright"))
        fields = base.analyze(html, settings, price_selector=target.get("price_selector"))
        result.in_stock = fields["in_stock"]
        result.price = fields["price"]
        result.price_text = fields["price_text"]
        result.dispatch = fields["dispatch"]
    except Exception as exc:  # noqa: BLE001 — one vendor failing must not abort the run
        result.error = f"{type(exc).__name__}: {exc}"
    return result
