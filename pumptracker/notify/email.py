"""Gmail SMTP email notifications (fallback channel).

Uses a Gmail account + app password over STARTTLS. The chat-side Gmail connector
cannot send from the unattended GitHub Actions job, so this authenticates directly.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

_SENDER_ENV = "GMAIL_ADDRESS"
_PASSWORD_ENV = "GMAIL_APP_PASSWORD"
_TO_ENV = "ALERT_EMAIL_TO"


def is_configured() -> bool:
    return bool(os.environ.get(_SENDER_ENV) and os.environ.get(_PASSWORD_ENV))


def send_email(subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True on success."""
    sender = os.environ.get(_SENDER_ENV)
    password = os.environ.get(_PASSWORD_ENV)
    if not sender or not password:
        log.warning("Gmail env vars missing; cannot send email.")
        return False

    # Default the recipient to the sender if ALERT_EMAIL_TO isn't set.
    recipient = os.environ.get(_TO_ENV) or sender

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)

    # App passwords are 16 chars; Google shows them with spaces which must be stripped.
    clean_password = password.replace(" ", "")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(sender, clean_password)
            server.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("Email send failed: %s", exc)
        return False
