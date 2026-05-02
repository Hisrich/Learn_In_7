"""
services/scheduler.py - APScheduler integration.

Uses BackgroundScheduler (runs in the same process as Flask).
For high-scale production, replace with Celery + Redis/RabbitMQ.

Why APScheduler over Celery here?
  - Zero external dependencies (no Redis/RabbitMQ)
  - Fine for < 10k users sending ~1 message/hour per active plan
  - Easy to swap: just change the job registration and keep daily_sender.py

The scheduler is initialised in app.py and passed the Flask app so the
job can run inside an application context.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import config

logger = logging.getLogger(__name__)

# Module-level scheduler instance (singleton)
scheduler = BackgroundScheduler(timezone="UTC")


def init_scheduler(app) -> None:
    """
    Register the daily-send job and start the scheduler.
    Safe to call multiple times (checks if already running).
    """
    if scheduler.running:
        logger.info("Scheduler already running — skipping re-init")
        return

    # Import here to avoid circular imports at module load time
    from tasks.daily_sender import send_due_messages

    scheduler.add_job(
        func=send_due_messages,
        args=[app],
        trigger=IntervalTrigger(seconds=config.SCHEDULER_INTERVAL_SECONDS),
        id="send_due_messages",
        name="Send due lesson messages",
        replace_existing=True,
        max_instances=1,          # prevent overlap if a run takes too long
        misfire_grace_time=300,   # allow up to 5 min late start
    )

    scheduler.start()
    logger.info(
        "Scheduler started. Job interval: %ds", config.SCHEDULER_INTERVAL_SECONDS
    )


def shutdown_scheduler() -> None:
    """Gracefully stop the scheduler (called on Flask teardown)."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")
