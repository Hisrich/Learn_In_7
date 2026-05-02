"""
services/gemini_service.py - Gemini API integration.

Responsibilities:
  - Build the prompt
  - Call the Gemini REST API
  - Parse and *strictly validate* the JSON response
  - Surface clear errors for the caller to handle

Design decisions:
  - Use the raw REST endpoint (requests) rather than the SDK so there
    is no extra dependency and the transport layer is transparent.
  - Generate once, store — never call Gemini more than once per user
    request, even on retries (content is stored before Day 1 is sent).
"""

import json
import logging
import time
from typing import Dict

import requests

from config import config

logger = logging.getLogger(__name__)

# ── Prompt template ────────────────────────────────────────────────────────────
PROMPT_TEMPLATE = """
Break the topic "{topic}" into a 7-day structured learning plan.

Each day must:
- Be 120–200 words
- Be engaging and easy to read
- Build progressively from beginner to advanced
- Avoid repetition
- Use emojis sparingly to improve readability

Return ONLY valid JSON with keys day1 to day7.
Do NOT include markdown code fences, comments, or any text outside the JSON object.

Example format:
{{
  "day1": "...",
  "day2": "...",
  "day3": "...",
  "day4": "...",
  "day5": "...",
  "day6": "...",
  "day7": "..."
}}
""".strip()

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{config.GEMINI_MODEL}:generateContent"
)

REQUIRED_KEYS = {f"day{i}" for i in range(1, 8)}


class GeminiError(Exception):
    """Raised when Gemini returns an unusable response."""


def generate_learning_plan(topic: str) -> Dict[str, str]:
    """
    Call Gemini and return a dict with keys day1..day7.

    Raises GeminiError on network failure, bad HTTP status, or invalid JSON.
    """
    prompt = PROMPT_TEMPLATE.format(topic=topic)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            # Low temperature → more deterministic, structured output
            "temperature": 0.7,
            "maxOutputTokens": 4096,
        },
    }

    logger.info("Calling Gemini for topic: '%s'", topic)
    start = time.monotonic()

    try:
        response = requests.post(
            GEMINI_URL,
            params={"key": config.GEMINI_API_KEY},
            json=payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise GeminiError(f"Network error calling Gemini: {exc}") from exc

    elapsed = time.monotonic() - start
    logger.info("Gemini responded in %.2fs (status %d)", elapsed, response.status_code)

    if response.status_code != 200:
        raise GeminiError(
            f"Gemini returned HTTP {response.status_code}: {response.text[:500]}"
        )

    raw_text = _extract_text(response.json())
    plan = _parse_and_validate(raw_text)
    logger.info("Successfully parsed 7-day plan for topic: '%s'", topic)
    return plan


def _extract_text(data: dict) -> str:
    """
    Pull the generated text out of the Gemini response envelope.
    Raises GeminiError if the expected structure is missing.
    """
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GeminiError(
            f"Unexpected Gemini response structure: {exc}\nResponse: {data}"
        ) from exc


def _parse_and_validate(raw: str) -> Dict[str, str]:
    """
    Strip any accidental markdown fences and parse JSON.
    Validate that all 7 day keys are present and non-empty.
    """
    # Remove ``` ... ``` wrappers if the model ignores the prompt.
    # We use a regex so we handle ```json, ``` json, ``` alone, etc.
    import re as _re
    cleaned = raw.strip()
    fence_pattern = _re.compile(
        r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", _re.DOTALL
    )
    match = fence_pattern.match(cleaned)
    if match:
        cleaned = match.group(1).strip()

    try:
        plan: dict = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GeminiError(
            f"Gemini output is not valid JSON: {exc}\nRaw output:\n{raw[:800]}"
        ) from exc

    if not isinstance(plan, dict):
        raise GeminiError("Expected a JSON object at the top level.")

    missing = REQUIRED_KEYS - plan.keys()
    if missing:
        raise GeminiError(f"Missing keys in Gemini response: {sorted(missing)}")

    # Ensure every day has non-trivial content
    for key in REQUIRED_KEYS:
        if not isinstance(plan[key], str) or len(plan[key].strip()) < 50:
            raise GeminiError(
                f"Content for '{key}' is missing or too short: {repr(plan[key][:80])}"
            )

    return {k: v.strip() for k, v in plan.items() if k in REQUIRED_KEYS}
