"""
utils/chunking.py - Safe text splitting for Telegram messages.

Telegram enforces a 4096-character limit per message.  This module
splits long text at sensible boundaries (paragraph → sentence → hard
cut) so we never silently truncate content.
"""

import re
import logging
from typing import List

logger = logging.getLogger(__name__)

# Telegram's documented max message length
TELEGRAM_MAX_LENGTH = 4096


def split_message(text: str, max_length: int = TELEGRAM_MAX_LENGTH) -> List[str]:
    """
    Split *text* into a list of strings each ≤ *max_length* characters.

    Split priority:
      1. Double newline (paragraph boundary)  — cleanest break
      2. Single newline                        — line boundary
      3. Sentence end (. ! ?)                  — readable break
      4. Word boundary (space)                 — last resort
      5. Hard cut                              — avoids infinite loop

    Returns a list with at least one element (even for empty input).
    """
    if not text:
        return [""]

    if len(text) <= max_length:
        return [text]

    chunks: List[str] = []
    remaining = text.strip()

    while len(remaining) > max_length:
        chunk = remaining[:max_length]

        # 1. Try paragraph break
        split_at = chunk.rfind("\n\n")

        # 2. Single newline
        if split_at == -1:
            split_at = chunk.rfind("\n")

        # 3. Sentence boundary
        if split_at == -1:
            match = re.search(r"[.!?]\s+", chunk[::-1])
            if match:
                split_at = max_length - match.start()

        # 4. Word boundary
        if split_at == -1:
            split_at = chunk.rfind(" ")

        # 5. Hard cut — avoids infinite loop on pathological input
        if split_at <= 0:
            split_at = max_length

        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    logger.debug("split_message: produced %d chunks", len(chunks))
    return chunks


def format_day_message(day: int, topic: str, content: str) -> str:
    """
    Wrap raw Gemini content in a readable Telegram message.

    Example output:
        📅 *Day 3 of 7 — Machine Learning Basics*

        <content>

        ────────────────────
        Type /status to see your progress.
    """
    header = f"📅 *Day {day} of 7 — {topic}*\n\n"
    footer = "\n\n────────────────────\nType /status to see your progress."
    return header + content + footer
