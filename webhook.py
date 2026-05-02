"""
routes/webhook.py - Telegram webhook endpoint.

All incoming updates from Telegram arrive here as HTTP POST requests.
This module is intentionally thin: it parses the update, delegates to
command handlers, and always returns HTTP 200 so Telegram doesn't retry.

Command handlers:
  /start   — welcome message + register user
  /learn   — generate & schedule 7-day plan
  /status  — show current progress
  /cancel  — cancel active plan
  <free text> — helpful fallback prompt
"""

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify

from models import db, UserProfile, LearningPlan, AdminLog
from telegram_service import parse_update, send_message, send_typing
from gemini_service import generate_learning_plan, GeminiError
from config import config

logger = logging.getLogger(__name__)

webhook_bp = Blueprint("webhook", __name__)

# ── Responses ──────────────────────────────────────────────────────────────────

WELCOME_TEXT = (
    "👋 *Welcome to the 7-Day Learning Bot!*\n\n"
    "I'll generate a personalised 7-day learning series on any topic "
    "and deliver one lesson per day.\n\n"
    "*Commands:*\n"
    "• /learn `<topic>` — Start a new 7-day series\n"
    "• /status — Check your current progress\n"
    "• /cancel — Stop your current plan\n\n"
    "_Example:_ /learn Machine Learning Basics"
)

HELP_TEXT = (
    "🤖 *I understand these commands:*\n\n"
    "/learn `<topic>` — Start a new 7-day learning series\n"
    "/status — See how far you've progressed\n"
    "/cancel — Cancel your current plan\n"
    "/start — Show the welcome message again\n\n"
    "Just send a topic after /learn and I'll do the rest!"
)


# ── Main webhook route ─────────────────────────────────────────────────────────

@webhook_bp.route("/webhook", methods=["POST"])
def webhook():
    """
    Receive a Telegram Update and dispatch to the appropriate handler.
    Always returns 200 — Telegram will retry on any other status code,
    which could cause duplicate processing.
    """
    data = request.get_json(silent=True)
    if not data:
        logger.warning("Received empty or non-JSON webhook payload")
        return jsonify({"ok": True}), 200

    update = parse_update(data)
    if not update:
        # Could be a channel post, poll, etc. — safely ignore
        return jsonify({"ok": True}), 200

    chat_id: int = update["chat_id"]
    command: str = update.get("command") or ""
    args: str = update.get("args") or ""
    text: str = update.get("text") or ""

    logger.info(
        "Update received: chat_id=%d command='%s' args='%s'",
        chat_id, command, args[:50],
    )

    # Ensure a UserProfile exists for this chat
    _upsert_user(chat_id, update.get("username"))

    try:
        if command == "/start":
            handle_start(chat_id)
        elif command == "/learn":
            handle_learn(chat_id, args)
        elif command == "/status":
            handle_status(chat_id)
        elif command == "/cancel":
            handle_cancel(chat_id)
        elif command == "/help":
            send_message(chat_id, HELP_TEXT)
        else:
            # Free-form text — guide the user
            send_message(
                chat_id,
                f"💡 Not sure what to do with that. Try:\n\n"
                f"/learn {text}\n\nor type /help for all commands.",
            )
    except Exception as exc:  # noqa: BLE001
        # Catch-all: log the error but never crash the webhook
        logger.exception("Unhandled error for chat_id=%d: %s", chat_id, exc)
        send_message(
            chat_id,
            "⚠️ Something went wrong on my end. Please try again in a moment.",
        )

    return jsonify({"ok": True}), 200


# ── Command handlers ───────────────────────────────────────────────────────────

def handle_start(chat_id: int) -> None:
    send_message(chat_id, WELCOME_TEXT)


def handle_learn(chat_id: int, topic: str) -> None:
    """
    1. Validate input
    2. Cancel any existing active plan
    3. Call Gemini (once — content is stored, not regenerated daily)
    4. Persist all 7 days to the DB
    5. Send Day 1 immediately
    6. Days 2–7 are scheduled and delivered by the background job
    """
    if not topic:
        send_message(
            chat_id,
            "📝 Please tell me *what* you'd like to learn!\n\n"
            "_Example:_ /learn Python for Beginners",
        )
        return

    if len(topic) > 200:
        send_message(chat_id, "⚠️ Topic is too long. Please keep it under 200 characters.")
        return

    # Cancel any ongoing plan so the user starts fresh
    _cancel_active_plan(chat_id, silent=True)

    # Show typing while we wait for Gemini (can take 5–15s)
    send_typing(chat_id)
    send_message(
        chat_id,
        f"🔍 Generating your 7-day learning plan for *{topic}*…\n"
        "This usually takes 10–20 seconds.",
    )

    try:
        plan_data = generate_learning_plan(topic)
    except GeminiError as exc:
        logger.error("Gemini error for chat_id=%d: %s", chat_id, exc)
        send_message(
            chat_id,
            "❌ I couldn't generate a plan right now. "
            "The AI service may be temporarily unavailable. Please try again.",
        )
        _log(chat_id, "GEMINI_ERROR", str(exc)[:500])
        return

    # Persist all 7 days
    now = datetime.now(timezone.utc)
    user = UserProfile.query.filter_by(chat_id=chat_id).first()

    for day_num in range(1, 8):
        key = f"day{day_num}"
        # Day 1 → now (sent immediately below), Day 2 → +1 day, etc.
        scheduled = now + timedelta(days=day_num - 1)

        plan_row = LearningPlan(
            chat_id=chat_id,
            user_id=user.id if user else None,
            topic=topic,
            day=day_num,
            content=plan_data[key],
            sent=False,
            scheduled_date=scheduled,
        )
        db.session.add(plan_row)

    try:
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.error("DB error saving plan for chat_id=%d: %s", chat_id, exc)
        send_message(chat_id, "❌ Failed to save your plan. Please try again.")
        return

    _log(chat_id, "PLAN_CREATED", topic)
    logger.info("Plan created for chat_id=%d topic='%s'", chat_id, topic)

    # ── Send Day 1 immediately ─────────────────────────────────────────
    day1_row = (
        LearningPlan.query
        .filter_by(chat_id=chat_id, topic=topic, day=1)
        .first()
    )
    if day1_row:
        from chunking import format_day_message
        msg = format_day_message(1, topic, plan_data["day1"])
        success = send_message(chat_id, msg)
        if success:
            day1_row.sent = True
            day1_row.sent_at = datetime.now(timezone.utc)
            day1_row.send_attempts = 1
            db.session.commit()
            _log(chat_id, "SEND_OK", f"Day 1 of '{topic}'")
        else:
            send_message(
                chat_id,
                "⚠️ Your plan is saved but I couldn't send Day 1 right now. "
                "I'll retry automatically.",
            )

    send_message(
        chat_id,
        f"✅ *Your plan is set!*\n\n"
        f"Days 2–7 will arrive once per day.\n"
        f"Use /status anytime to check your progress.",
    )


def handle_status(chat_id: int) -> None:
    """Show how many days have been sent vs remaining."""
    # Find the most recently created active plan (unsent days remaining)
    latest_topic = (
        db.session.query(LearningPlan.topic)
        .filter_by(chat_id=chat_id)
        .order_by(LearningPlan.created_at.desc())
        .first()
    )

    if not latest_topic:
        send_message(
            chat_id,
            "📭 You don't have any learning plan yet.\n\n"
            "Start one with /learn followed by a topic!",
        )
        return

    topic = latest_topic[0]
    rows = (
        LearningPlan.query
        .filter_by(chat_id=chat_id, topic=topic)
        .order_by(LearningPlan.day)
        .all()
    )

    sent_count = sum(1 for r in rows if r.sent)
    remaining = 7 - sent_count

    if remaining == 0:
        send_message(
            chat_id,
            f"🎓 You've completed your plan on *{topic}*!\n\n"
            "Start a new one with /learn.",
        )
        return

    # Build a visual progress bar
    filled = "🟩" * sent_count
    empty = "⬜" * remaining
    next_day = next((r for r in rows if not r.sent), None)
    next_date = (
        next_day.scheduled_date.strftime("%Y-%m-%d %H:%M UTC")
        if next_day
        else "soon"
    )

    send_message(
        chat_id,
        f"📊 *Progress — {topic}*\n\n"
        f"{filled}{empty}  Day {sent_count} of 7 complete\n\n"
        f"📅 Next lesson: {next_date}",
    )


def handle_cancel(chat_id: int) -> None:
    """Cancel all unsent days for this user."""
    cancelled = _cancel_active_plan(chat_id, silent=False)
    if cancelled > 0:
        send_message(
            chat_id,
            f"🛑 Cancelled! {cancelled} remaining lesson(s) removed.\n\n"
            "Start a new plan anytime with /learn.",
        )
        _log(chat_id, "PLAN_CANCELLED", f"{cancelled} days removed")
    else:
        send_message(
            chat_id,
            "ℹ️ You don't have any active learning plan to cancel.",
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _upsert_user(chat_id: int, username: str = None) -> UserProfile:
    """Create or update a UserProfile row."""
    user = UserProfile.query.filter_by(chat_id=chat_id).first()
    if not user:
        user = UserProfile(chat_id=chat_id, username=username)
        db.session.add(user)
    else:
        if username and user.username != username:
            user.username = username
    try:
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
    return user


def _cancel_active_plan(chat_id: int, silent: bool = True) -> int:
    """
    Delete all unsent LearningPlan rows for *chat_id*.
    Returns the number of rows deleted.
    """
    unsent = LearningPlan.query.filter_by(chat_id=chat_id, sent=False).all()
    count = len(unsent)
    for row in unsent:
        db.session.delete(row)
    try:
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        return 0
    return count


def _log(chat_id: int, event: str, detail: str = "") -> None:
    """Write to AdminLog (best-effort)."""
    try:
        db.session.add(AdminLog(chat_id=chat_id, event=event, detail=detail))
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
