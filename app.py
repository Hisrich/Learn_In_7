"""
app.py - Flask application factory and entry point.

Usage:
  python app.py               # development
  gunicorn app:app            # production

The create_app() factory pattern makes the app easily testable and
lets us avoid circular imports (models import db, which is initialised
here rather than at module level).
"""

import atexit
import logging
import sys

from flask import Flask, jsonify

from config import config
from models import db
from webhook import webhook_bp
from scheduler import init_scheduler, shutdown_scheduler
from telegram_service import register_webhook

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        # Uncomment to also log to a file:
        # logging.FileHandler("bot.log"),
    ],
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Application factory — create and configure the Flask app."""
    app = Flask(__name__)

    # ── Configuration ──────────────────────────────────────────────────
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = config.DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ── Database ───────────────────────────────────────────────────────
    db.init_app(app)
    with app.app_context():
        db.create_all()
        logger.info("Database tables created / verified")

    # ── Blueprints ─────────────────────────────────────────────────────
    app.register_blueprint(webhook_bp)

    # ── Health-check endpoint ──────────────────────────────────────────
    @app.route("/health", methods=["GET"])
    def health():
        """Simple liveness probe for load balancers / uptime monitors."""
        return jsonify({"status": "ok", "service": "telegram-learning-bot"}), 200

    # ── Scheduler ─────────────────────────────────────────────────────
    init_scheduler(app)
    atexit.register(shutdown_scheduler)

    # ── Register Telegram webhook ──────────────────────────────────────
    # Done here so every fresh deploy automatically updates the webhook URL
    with app.app_context():
        success = register_webhook()
        if not success:
            logger.warning(
                "Webhook registration failed. "
                "Check TELEGRAM_BOT_TOKEN and WEBHOOK_URL in your .env file."
            )

    logger.info("Flask app ready on port %d", config.PORT)
    return app


# Create the module-level app instance (used by gunicorn)
app = create_app()


if __name__ == "__main__":
    # Development server — for production use gunicorn
    app.run(
        host="0.0.0.0",
        port=config.PORT,
        debug=config.DEBUG,
        # use_reloader=False prevents the scheduler from spawning twice
        use_reloader=False,
    )
