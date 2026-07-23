"""Core data types shared across scrapers, notifiers and the orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ProductResult:
    """The outcome of checking a single watched target (one product at one vendor)."""

    target_id: str          # stable id from config, e.g. "onbuy-sx925"
    vendor: str             # human label, e.g. "OnBuy"
    product: str            # human label, e.g. "Intex SX925 sand filter pump"
    url: str                # direct product URL to buy from

    # Result of the check. `in_stock is None` means the check itself failed
    # (blocked / timed out) — treated as "unknown", never as a stock transition.
    in_stock: Optional[bool] = None
    price: Optional[float] = None          # numeric GBP, e.g. 116.91
    price_text: Optional[str] = None       # raw as shown, e.g. "£116.91"
    dispatch: Optional[str] = None         # generic dispatch/delivery note if found
    error: Optional[str] = None            # populated when the check failed
    checked_at: str = field(default_factory=_now_iso)
    debug: Optional[str] = None            # only set in debug mode; never persisted to state

    @property
    def ok(self) -> bool:
        """True when the check completed (regardless of stock state)."""
        return self.error is None and self.in_stock is not None

    def price_display(self) -> str:
        if self.price_text:
            return self.price_text
        if self.price is not None:
            return f"£{self.price:.2f}"
        return "—"

    def status_display(self) -> str:
        if self.error is not None:
            return "ERROR"
        if self.in_stock is None:
            return "UNKNOWN"
        return "IN STOCK" if self.in_stock else "out of stock"

    def to_dict(self) -> dict:
        return asdict(self)
