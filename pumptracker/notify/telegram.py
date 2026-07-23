"""Telegram Bot API push notifications (primary channel)."""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
_CHAT_ENV = "TELEGRAM_CHAT_ID"


def is_configured() -> bool:
    return bool(os.environ.get(_TOKEN_ENV) and os.environ.get(_CHAT_ENV))


def send_message(text: str) -> bool:
    """Send a plain-text message. Returns True on success."""
    import httpx

    token = os.environ.get(_TOKEN_ENV)
    chat_id = os.environ.get(_CHAT_ENV)
    if not token or not chat_id:
        log.warning("Telegram env vars missing; cannot send.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
    }
    try:
        resp = httpx.post(url, json=payload, timeout=20)
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        # Surface Telegram's error body if there is one — it explains most failures.
        detail = getattr(getattr(exc, "response", None), "text", "")
        log.error("Telegram send failed: %s %s", exc, detail)
        return False
