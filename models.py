"""
models.py - SQLAlchemy ORM models.

Designed to work with both SQLite (dev) and PostgreSQL (prod).
All timestamps are stored in UTC; timezone conversion happens at
the application layer if needed.
"""

from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class UserProfile(db.Model):
    """
    Stores per-user preferences (e.g., timezone).
    Created or updated on first /start interaction.
    """

    __tablename__ = "user_profiles"

    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    username = db.Column(db.String(128), nullable=True)
    timezone = db.Column(db.String(64), nullable=False, default="UTC")
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # Relationship — one user can have many learning plans (one active at a time)
    plans = db.relationship(
        "LearningPlan", back_populates="user", lazy="dynamic"
    )

    def __repr__(self) -> str:
        return f"<UserProfile chat_id={self.chat_id}>"


class LearningPlan(db.Model):
    """
    One row per *day* of a 7-day learning series.

    Design decision: store individual days rather than a single JSON blob
    so we can query/update each day independently without deserializing
    the whole plan. Each day gets its own scheduled_date so the scheduler
    can simply do:

        WHERE sent = false AND scheduled_date <= NOW()
    """

    __tablename__ = "learning_plans"

    id = db.Column(db.Integer, primary_key=True)

    # Telegram chat_id — BigInteger covers both user IDs and group IDs
    chat_id = db.Column(db.BigInteger, nullable=False, index=True)

    # Foreign key to UserProfile for convenient joins
    user_id = db.Column(
        db.Integer, db.ForeignKey("user_profiles.id"), nullable=True
    )
    user = db.relationship("UserProfile", back_populates="plans")

    # Topic the user requested (stored for /status display)
    topic = db.Column(db.String(512), nullable=False)

    # 1 – 7
    day = db.Column(db.Integer, nullable=False)

    # The actual lesson content from Gemini
    content = db.Column(db.Text, nullable=False)

    # Has this day's message been successfully sent?
    sent = db.Column(db.Boolean, nullable=False, default=False, index=True)

    # Number of send attempts (for retry tracking)
    send_attempts = db.Column(db.Integer, nullable=False, default=0)

    # UTC datetime when this day should be delivered
    scheduled_date = db.Column(
        db.DateTime(timezone=True), nullable=False, index=True
    )

    # When the record was created
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow
    )

    # When it was actually sent (null until delivered)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Composite index for the scheduler query
    __table_args__ = (
        db.Index("ix_unsent_scheduled", "sent", "scheduled_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<LearningPlan chat_id={self.chat_id} "
            f"topic='{self.topic[:30]}' day={self.day} sent={self.sent}>"
        )


class AdminLog(db.Model):
    """
    Lightweight audit log for key bot events (errors, sends, cancels).
    Useful for debugging in production without tailing logs.
    """

    __tablename__ = "admin_logs"

    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.BigInteger, nullable=True)
    event = db.Column(db.String(64), nullable=False)   # e.g. "SEND_OK", "SEND_FAIL"
    detail = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow
    )

    def __repr__(self) -> str:
        return f"<AdminLog event={self.event} chat_id={self.chat_id}>"
