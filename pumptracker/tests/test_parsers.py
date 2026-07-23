"""Offline tests for page analysis and stock-transition logic.

These run against saved HTML fixtures — no network — so they stay stable and
catch regressions in stock/price detection when a vendor's layout drifts.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from pumptracker.scrapers import base
from pumptracker.main import _is_new_stock, _merge_state
from pumptracker.models import ProductResult

_PKG = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _settings() -> dict:
    with open(_PKG / "config.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["settings"]


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_in_stock_page_detected():
    fields = base.analyze(_load("onbuy_in_stock.html"), _settings())
    assert fields["in_stock"] is True
    assert fields["price"] == 110.00           # spare-part £8.99 correctly ignored
    assert "dispatch" in (fields["dispatch"] or "").lower()


def test_sold_out_takes_precedence_over_add_to_basket():
    # Page has both "SOLD OUT" and an add-to-basket button; OOS must win.
    fields = base.analyze(_load("heatpumps4pools_sold_out.html"), _settings())
    assert fields["in_stock"] is False
    assert fields["price"] == 130.00


def test_amazon_currently_unavailable():
    fields = base.analyze(_load("amazon_unavailable.html"), _settings())
    assert fields["in_stock"] is False


def test_extract_price_band_filtering():
    settings = _settings()
    _, text = "", "Now £8.99 was £199.99"
    price, price_text = base.extract_price("", text, settings)
    assert price == 199.99                      # £8.99 below plausible band, skipped
    assert price_text == "£199.99"


def test_detect_stock_unknown_when_no_markers():
    assert base.detect_stock("just some text with no signals", _settings()) is None


def test_new_stock_only_on_transition():
    r = ProductResult("t", "V", "P", "http://x", in_stock=True)
    assert _is_new_stock(r, None) is True                     # first time seen in stock
    assert _is_new_stock(r, {"in_stock": False}) is True      # OOS -> in stock
    assert _is_new_stock(r, {"in_stock": True}) is False      # already in stock, no re-alert


def test_error_result_never_alerts_and_carries_forward_state():
    err = ProductResult("t", "V", "P", "http://x", error="Timeout")
    prev = {"in_stock": True, "price": 130.0, "last_in_stock_at": "2026-07-01T00:00:00+00:00"}
    assert _is_new_stock(err, prev) is False
    merged = _merge_state(err, prev, alerted=False)
    # A failed check must not wipe the last known stock state.
    assert merged["in_stock"] is True
    assert merged["price"] == 130.0
