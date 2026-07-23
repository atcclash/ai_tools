"""Alert formatting and dispatch.

Telegram is the primary channel, Gmail SMTP the fallback. Both are optional:
if a channel's env vars are unset it's simply skipped, so the tracker still
runs (and logs) with no notifiers configured.
"""

from __future__ import annotations

import logging
from typing import Sequence

from ..models import ProductResult
from . import telegram, email as email_mod

log = logging.getLogger(__name__)


def format_alert(results: Sequence[ProductResult]) -> tuple[str, str]:
    """Build (subject, body) for a batch of now-in-stock results."""
    n = len(results)
    subject = (
        f"Pool pump IN STOCK: {results[0].product} at {results[0].vendor}"
        if n == 1
        else f"Pool pump IN STOCK: {n} listings available"
    )
    lines = ["🏊 Pool pump availability alert", ""]
    for r in results:
        lines.append(f"• {r.product}")
        lines.append(f"  Vendor: {r.vendor}")
        lines.append(f"  Price:  {r.price_display()}")
        if r.dispatch:
            lines.append(f"  Dispatch: {r.dispatch}")
        lines.append(f"  Buy: {r.url}")
        lines.append("")
    lines.append("Prices/stock can change fast — confirm on the page before paying.")
    return subject, "\n".join(lines)


def notify(subject: str, body: str, *, dry_run: bool = False) -> None:
    """Send an alert via every configured channel."""
    if dry_run:
        log.info("[dry-run] would send alert:\n%s\n%s", subject, body)
        return

    sent_any = False
    if telegram.is_configured():
        if telegram.send_message(body):
            sent_any = True
            log.info("Telegram alert sent.")
    else:
        log.info("Telegram not configured — skipping.")

    if email_mod.is_configured():
        if email_mod.send_email(subject, body):
            sent_any = True
            log.info("Email alert sent.")
    else:
        log.info("Email not configured — skipping.")

    if not sent_any:
        log.warning("No notifier delivered the alert (none configured or all failed).")


def test_notify() -> None:
    """Send a sample message on every configured channel to verify setup."""
    subject = "Pool pump tracker — test alert"
    body = (
        "✅ This is a test from your pool pump tracker.\n\n"
        "If you can read this, this channel is set up correctly.\n"
        "You'll get a real alert when an Intex SX925 (or equivalent) comes into stock."
    )
    if not telegram.is_configured() and not email_mod.is_configured():
        log.warning("No notifiers configured — set the Telegram and/or Gmail env vars.")
    notify(subject, body, dry_run=False)
