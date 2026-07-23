"""One-time helper to find your Telegram chat id.

Usage:
    1. Create a bot with @BotFather in Telegram and copy its token.
    2. Open a chat with your new bot and send it any message (e.g. "hi").
    3. Run:  TELEGRAM_BOT_TOKEN=xxationyyy python -m pumptracker.scripts.get_telegram_chat_id
       (or pass the token as the first argument)
    4. Copy the printed chat id into the TELEGRAM_CHAT_ID secret.
"""

from __future__ import annotations

import os
import sys

import httpx


def main() -> int:
    token = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Provide the bot token as an argument or via TELEGRAM_BOT_TOKEN.")
        return 1

    resp = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20)
    resp.raise_for_status()
    data = resp.json()

    updates = data.get("result", [])
    if not updates:
        print(
            "No messages found. Send your bot a message in Telegram first, "
            "then re-run this script."
        )
        return 1

    seen: dict[int, str] = {}
    for upd in updates:
        chat = (upd.get("message") or upd.get("channel_post") or {}).get("chat", {})
        if "id" in chat:
            label = chat.get("username") or chat.get("title") or chat.get("first_name") or ""
            seen[chat["id"]] = label

    print("Found chat id(s):")
    for chat_id, label in seen.items():
        print(f"  {chat_id}  {label}".rstrip())
    print("\nUse the id above as your TELEGRAM_CHAT_ID.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
