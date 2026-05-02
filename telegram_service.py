"""
services/telegram_service.py - Telegram Bot API client.

Responsibilities:
  - Register/update the webhook
  - Send messages (with retry + rate-limit logic)
  - Parse incoming Update objects

Design decisions:
  - All outbound calls go through send_message() which handles retries
    and rate-limiting so the rest of the codebase stays clean.
  - We use MarkdownV2 parse_mode for rich formatting. The helper
    escape_markdown() handles special characters automatically.
"""

import logging
import time
from typing import Optional

import requests

from config import config
from chunking import split_message

logger = logging.getLogger(__name__)

# Characters that must be escaped in MarkdownV2
_MD_SPECIAL = r"\_*[]()~`>#+-=|{}.!"


def escape_markdown(text: str) -> str:
    """Escape special MarkdownV2 characters in plain text."""
    for char in _MD_SPECIAL:
        text = text.replace(char, f"\\{char}")
    return text


def register_webhook() -> bool:
    """
    Tell Telegram where to POST incoming updates.
    Call this once at startup (idempotent — safe to call on every deploy).
    """
    url = f"{config.TELEGRAM_API_BASE}/setWebhook"
    payload = {
        "url": config.WEBHOOK_URL,
        "allowed_updates": ["message"],
        "drop_pending_updates": True,   # ignore stale updates from downtime
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get("ok"):
            logger.info("Webhook registered: %s", config.WEBHOOK_URL)
            return True
        logger.error("Failed to register webhook: %s", data)
        return False
    except requests.RequestException as exc:
        logger.error("Network error registering webhook: %s", exc)
        return False


def send_message(
    chat_id: int,
    text: str,
    parse_mode: str = "Markdown",
    retry: int = 0,
) -> bool:
    """
    Send a text message to *chat_id*.

    - Automatically splits messages that exceed Telegram's 4096-char limit.
    - Retries up to config.MAX_SEND_RETRIES times with exponential back-off.
    - Returns True if *all* chunks were delivered successfully.
    """
    chunks = split_message(text)
    success = True

    for i, chunk in enumerate(chunks):
        ok = _send_single(chat_id, chunk, parse_mode, retry)
        if not ok:
            logger.error(
                "Failed to send chunk %d/%d to chat_id=%d", i + 1, len(chunks), chat_id
            )
            success = False
            break  # stop sending further chunks if one fails

        # Respect global rate limit between chunks
        if len(chunks) > 1:
            time.sleep(1 / config.RATE_LIMIT_PER_SECOND)

    return success


def _send_single(
    chat_id: int,
    text: str,
    parse_mode: str,
    attempt: int,
) -> bool:
    """Internal: send one chunk with retry logic."""
    url = f"{config.TELEGRAM_API_BASE}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }

    for attempt_num in range(config.MAX_SEND_RETRIES):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()

            if data.get("ok"):
                return True

            # 429 Too Many Requests — respect Telegram's retry_after
            if resp.status_code == 429:
                retry_after = data.get("parameters", {}).get("retry_after", 5)
                logger.warning(
                    "Rate-limited by Telegram, sleeping %ds", retry_after
                )
                time.sleep(retry_after)
                continue

            # 400 Bad Request — usually a parse_mode issue; retry without formatting
            if resp.status_code == 400 and parse_mode != "":
                logger.warning(
                    "Markdown parse error for chat_id=%d, retrying as plain text", chat_id
                )
                payload["parse_mode"] = ""
                continue

            logger.error(
                "Telegram sendMessage error (attempt %d): %s",
                attempt_num + 1,
                data,
            )

        except requests.RequestException as exc:
            logger.error(
                "Network error sending to chat_id=%d (attempt %d): %s",
                chat_id, attempt_num + 1, exc,
            )

        # Exponential back-off: 5s, 10s, 20s, …
        wait = config.RETRY_BACKOFF_SECONDS * (2 ** attempt_num)
        logger.info("Retrying in %ds…", wait)
        time.sleep(wait)

    return False


def send_typing(chat_id: int) -> None:
    """Show 'typing…' indicator — fire-and-forget, no retry needed."""
    try:
        requests.post(
            f"{config.TELEGRAM_API_BASE}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )
    except requests.RequestException:
        pass  # cosmetic feature; swallow silently


# ── Update parsing helpers ─────────────────────────────────────────────────────

def parse_update(data: dict) -> Optional[dict]:
    """
    Extract the essential fields from a Telegram Update object.

    Returns a simplified dict:
        {
            "chat_id": int,
            "username": str | None,
            "text": str,               # raw message text
            "command": str | None,     # "/start", "/learn", etc.
            "args": str,               # text after the command
        }
    or None if the update has no message text.
    """
    message = data.get("message") or data.get("edited_message")
    if not message:
        return None

    text: str = message.get("text", "").strip()
    if not text:
        return None

    chat = message.get("chat", {})
    from_user = message.get("from", {})

    command: Optional[str] = None
    args: str = ""

    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        # Strip bot username suffix (e.g. /start@MyBot → /start)
        command = parts[0].split("@")[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

    return {
        "chat_id": chat.get("id"),
        "username": from_user.get("username"),
        "text": text,
        "command": command,
        "args": args,
    }
