"""
tasks/daily_sender.py - Background job: send due lesson messages.

This module contains the core logic executed by the scheduler every hour.

Algorithm:
  1. Query all LearningPlan rows where sent=False AND scheduled_date <= NOW()
  2. For each row, send the message via Telegram
  3. On success: mark sent=True, record sent_at
  4. On failure: increment send_attempts; if attempts >= MAX_SEND_RETRIES,
     mark as permanently failed (sent=True with a note) to prevent loops
  5. Log every event to AdminLog for auditability
"""

import logging
from datetime import datetime, timezone

from models import db, LearningPlan, AdminLog
from telegram_service import send_message
from chunking import format_day_message
from config import config

logger = logging.getLogger(__name__)


def send_due_messages(app) -> None:
    """
    Entry point called by the scheduler.
    Runs inside the Flask app context so SQLAlchemy sessions work correctly.
    """
    with app.app_context():
        _process_due_messages()


def _process_due_messages() -> None:
    """Query and dispatch all messages whose scheduled_date has passed."""
    now = datetime.now(timezone.utc)

    due_plans = (
        LearningPlan.query
        .filter(
            LearningPlan.sent == False,           # noqa: E712
            LearningPlan.scheduled_date <= now,
            LearningPlan.send_attempts < config.MAX_SEND_RETRIES,
        )
        .order_by(LearningPlan.scheduled_date.asc())
        .all()
    )

    if not due_plans:
        logger.debug("No due messages at %s", now.isoformat())
        return

    logger.info("Found %d due message(s) to send", len(due_plans))

    for plan in due_plans:
        _deliver(plan)


def _deliver(plan: LearningPlan) -> None:
    """Attempt to send one day's lesson and update the database."""
    plan.send_attempts += 1

    message_text = format_day_message(plan.day, plan.topic, plan.content)

    logger.info(
        "Sending Day %d to chat_id=%d (attempt %d)",
        plan.day, plan.chat_id, plan.send_attempts,
    )

    success = send_message(plan.chat_id, message_text)

    if success:
        plan.sent = True
        plan.sent_at = datetime.now(timezone.utc)
        _log_event(plan.chat_id, "SEND_OK", f"Day {plan.day} of '{plan.topic}'")
        logger.info("✓ Day %d sent to chat_id=%d", plan.day, plan.chat_id)

        # If this was the last day, send a completion message
        if plan.day == 7:
            _send_completion_message(plan.chat_id, plan.topic)

    else:
        if plan.send_attempts >= config.MAX_SEND_RETRIES:
            # Mark as permanently failed to stop retry loops.
            # An operator can manually reset send_attempts to re-queue.
            plan.sent = True
            detail = (
                f"Permanently failed after {plan.send_attempts} attempts. "
                f"Day {plan.day} of '{plan.topic}'"
            )
            _log_event(plan.chat_id, "SEND_PERM_FAIL", detail)
            logger.error("✗ Permanent failure for chat_id=%d Day %d", plan.chat_id, plan.day)
        else:
            _log_event(
                plan.chat_id,
                "SEND_FAIL",
                f"Attempt {plan.send_attempts} failed. Day {plan.day}",
            )
            logger.warning(
                "✗ Send failed (attempt %d), will retry. chat_id=%d Day %d",
                plan.send_attempts, plan.chat_id, plan.day,
            )

    try:
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        logger.error("DB commit error after send: %s", exc)


def _send_completion_message(chat_id: int, topic: str) -> None:
    """Send a congratulatory message when the 7-day series finishes."""
    text = (
        f"🎉 *Congratulations!*\n\n"
        f"You've completed your 7-day learning series on *{topic}*!\n\n"
        f"Ready for a new topic? Just send /learn followed by your next subject.\n"
        f"Type /start to see all available commands."
    )
    send_message(chat_id, text)
    _log_event(chat_id, "SERIES_COMPLETE", topic)


def _log_event(chat_id: int, event: str, detail: str = "") -> None:
    """Write a row to AdminLog (best-effort — never raises)."""
    try:
        entry = AdminLog(chat_id=chat_id, event=event, detail=detail)
        db.session.add(entry)
        # Don't commit here — caller commits after updating LearningPlan
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not write AdminLog: %s", exc)
