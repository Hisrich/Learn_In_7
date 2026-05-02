# 📚 Telegram 7-Day Learning Bot

A production-ready Telegram bot that generates personalised 7-day learning series using the Gemini API and delivers one lesson per day — automatically.

---

## Table of Contents

1. [Features](#features)
2. [Architecture Overview](#architecture-overview)
3. [Project Structure](#project-structure)
4. [Prerequisites](#prerequisites)
5. [Local Setup](#local-setup)
6. [Running Locally](#running-locally)
7. [Deployment Guide](#deployment-guide)
   - [Render (recommended)](#render-recommended)
   - [VPS / DigitalOcean](#vps--digitalocean)
8. [Bot Commands](#bot-commands)
9. [How It Works](#how-it-works)
10. [Configuration Reference](#configuration-reference)
11. [Database Schema](#database-schema)
12. [Scaling to Production](#scaling-to-production)
13. [Troubleshooting](#troubleshooting)

---

## Features

- **One-command setup** — `/learn Machine Learning` starts a full 7-day course
- **AI-generated content** — Gemini creates a structured, progressive curriculum
- **Daily delivery** — one lesson per day via Telegram, not a wall of text
- **Persistent storage** — SQLite (dev) or PostgreSQL (prod) via SQLAlchemy
- **Background scheduling** — APScheduler checks for due messages every hour
- **Retry logic** — failed sends are automatically retried up to 3 times
- **Rate limiting** — respects Telegram's API limits
- **Admin logging** — every key event is recorded in the database
- **Health endpoint** — `/health` for uptime monitors
- **Webhook-based** — no polling, zero idle CPU usage

---

## Architecture Overview

```
Telegram User
     │
     │  HTTPS POST (Update)
     ▼
┌─────────────┐
│  Flask App  │  /webhook endpoint
│  (app.py)   │
└──────┬──────┘
       │
       ├─── parse_update()        routes/webhook.py
       │
       ├─── /learn ──────────────► gemini_service.py ──► Gemini API
       │         │                      │
       │         │              generate_learning_plan()
       │         │                      │
       │         └──────────────► Save 7 rows to DB
       │                          Send Day 1 immediately
       │
       └─── APScheduler (every hour)
                 │
                 ▼
            daily_sender.py
                 │
            Query: sent=False AND scheduled_date <= NOW()
                 │
                 ▼
            telegram_service.py ──► Telegram API
                 │
            Mark sent=True in DB
```

---

## Project Structure

```
telegram-learning-bot/
├── app.py                   # Flask factory & entry point
├── config.py                # All settings from env vars
├── models.py                # SQLAlchemy ORM models
├── requirements.txt
├── Procfile                 # For Render / Heroku
├── render.yaml              # Render.com blueprint
├── .env.example             # Template — copy to .env
├── .gitignore
│
├── routes/
│   └── webhook.py           # Telegram webhook + command handlers
│
├── services/
│   ├── gemini_service.py    # Gemini API client + prompt engineering
│   ├── telegram_service.py  # Telegram API client (send, register webhook)
│   └── scheduler.py         # APScheduler setup
│
├── tasks/
│   └── daily_sender.py      # Background job: find & send due messages
│
└── utils/
    └── chunking.py          # Safe Telegram message splitting
```

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.10+ | Runtime |
| pip | latest | Package manager |
| ngrok (local dev) | latest | Expose localhost to Telegram |
| Telegram account | — | Create a bot via @BotFather |
| Google AI Studio | — | Get a Gemini API key |

---

## Local Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/yourname/telegram-learning-bot.git
cd telegram-learning-bot

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Create your Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** (format: `123456789:ABCdef...`)

### 3. Get a Gemini API key

1. Go to [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Click **Create API key**
3. Copy the key

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmnOPQrstUVWxyz
GEMINI_API_KEY=AIzaSy...
WEBHOOK_URL=https://abc123.ngrok.io/webhook   # filled in next step
SECRET_KEY=some-long-random-string
```

### 5. Expose localhost with ngrok

Telegram requires a public HTTPS URL to POST updates to. ngrok creates a secure tunnel:

```bash
# In a separate terminal
ngrok http 5000
```

Copy the **Forwarding** URL (e.g. `https://abc123.ngrok.io`) and update `.env`:

```env
WEBHOOK_URL=https://abc123.ngrok.io/webhook
```

---

## Running Locally

```bash
# Make sure your virtual environment is active
source venv/bin/activate

python app.py
```

You should see output like:

```
2024-01-15 10:00:00 [INFO] app: Database tables created / verified
2024-01-15 10:00:00 [INFO] services.scheduler: Scheduler started. Job interval: 3600s
2024-01-15 10:00:00 [INFO] services.telegram_service: Webhook registered: https://abc123.ngrok.io/webhook
2024-01-15 10:00:00 [INFO] app: Flask app ready on port 5000
```

Open Telegram, find your bot, and send `/start`.

### Verify the webhook is registered

```bash
curl https://api.telegram.org/bot<YOUR_TOKEN>/getWebhookInfo
```

Expected response includes `"url": "https://abc123.ngrok.io/webhook"`.

---

## Deployment Guide

### Render (recommended)

Render offers free hosting with automatic HTTPS — ideal for this bot.

#### Option A: One-click with render.yaml

1. Push your code to a GitHub repository (make sure `.env` is in `.gitignore`)
2. Go to [https://render.com](https://render.com) → **New** → **Blueprint**
3. Connect your GitHub repo — Render will detect `render.yaml` automatically
4. Set the secret environment variables in the Render dashboard:
   - `TELEGRAM_BOT_TOKEN`
   - `GEMINI_API_KEY`
   - `WEBHOOK_URL` → set to `https://<your-render-service-name>.onrender.com/webhook`
5. Click **Deploy**

#### Option B: Manual setup

1. **New Web Service** → connect your GitHub repo
2. Build command: `pip install -r requirements.txt`
3. Start command: `gunicorn app:app --workers 1 --threads 2 --bind 0.0.0.0:$PORT --timeout 120`
4. Add all environment variables from `.env.example`
5. Add a **PostgreSQL** database and set `DATABASE_URL` to the internal connection string

> ⚠️ **Free tier caveat**: Render free tier spins down after 15 minutes of inactivity.
> The scheduler runs inside the web process — upgrade to the **Starter** plan ($7/mo)
> for always-on service, or use an external cron ping (e.g. UptimeRobot) to keep it alive.

---

### VPS / DigitalOcean

For full control, deploy to any Linux VPS (Ubuntu 22.04 recommended).

#### 1. Provision the server

```bash
# SSH into your VPS
ssh root@your-server-ip

# Create a non-root user
adduser botuser
usermod -aG sudo botuser
su - botuser
```

#### 2. Install dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip nginx certbot python3-certbot-nginx git
```

#### 3. Clone and configure

```bash
git clone https://github.com/yourname/telegram-learning-bot.git
cd telegram-learning-bot

python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install psycopg2-binary  # if using PostgreSQL

cp .env.example .env
nano .env   # fill in all values
```

#### 4. Set up a systemd service

```bash
sudo nano /etc/systemd/system/learningbot.service
```

Paste:

```ini
[Unit]
Description=Telegram Learning Bot
After=network.target

[Service]
User=botuser
WorkingDirectory=/home/botuser/telegram-learning-bot
Environment="PATH=/home/botuser/telegram-learning-bot/venv/bin"
ExecStart=/home/botuser/telegram-learning-bot/venv/bin/gunicorn \
    app:app \
    --workers 1 \
    --threads 2 \
    --bind 127.0.0.1:5000 \
    --timeout 120 \
    --access-logfile /home/botuser/telegram-learning-bot/access.log \
    --error-logfile /home/botuser/telegram-learning-bot/error.log
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable learningbot
sudo systemctl start learningbot
sudo systemctl status learningbot
```

#### 5. Configure Nginx as a reverse proxy

```bash
sudo nano /etc/nginx/sites-available/learningbot
```

Paste:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/learningbot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### 6. Enable HTTPS with Let's Encrypt

```bash
sudo certbot --nginx -d your-domain.com
# Follow prompts — certbot auto-updates the nginx config
```

#### 7. Update WEBHOOK_URL and redeploy

```bash
# Edit .env
nano .env
# Set: WEBHOOK_URL=https://your-domain.com/webhook

sudo systemctl restart learningbot
```

---

## Bot Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Show welcome message | `/start` |
| `/learn <topic>` | Start a new 7-day series | `/learn Python for Beginners` |
| `/status` | Show current progress | `/status` |
| `/cancel` | Stop the current plan | `/cancel` |
| `/help` | List all commands | `/help` |

---

## How It Works

### User flow

```
User: /learn Machine Learning Basics
         │
         ▼
Bot calls Gemini once with structured prompt
         │
         ▼
Gemini returns JSON: { "day1": "...", ..., "day7": "..." }
         │
         ▼
Bot validates JSON (all 7 keys, minimum length)
         │
         ▼
Bot saves 7 rows to learning_plans table:
  Day 1 → scheduled_date = NOW
  Day 2 → scheduled_date = NOW + 1 day
  ...
  Day 7 → scheduled_date = NOW + 6 days
         │
         ▼
Bot sends Day 1 immediately
         │
         ▼
APScheduler runs every hour:
  → SELECT * WHERE sent=false AND scheduled_date <= NOW()
  → Sends each due message
  → Marks sent=true
```

### Scheduling guarantee

- Content is generated **once** and stored — no repeated API calls
- Each day has a dedicated `scheduled_date` — simple, auditable
- `send_attempts` counter prevents infinite retry loops
- `sent_at` records exact delivery time for debugging

---

## Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | From @BotFather |
| `WEBHOOK_URL` | ✅ | — | Public HTTPS URL + `/webhook` |
| `GEMINI_API_KEY` | ✅ | — | From Google AI Studio |
| `SECRET_KEY` | ✅ | `change-me` | Flask session secret |
| `DATABASE_URL` | ❌ | `sqlite:///learning_bot.db` | SQLAlchemy connection string |
| `GEMINI_MODEL` | ❌ | `gemini-2.0-flash` | Gemini model name |
| `SCHEDULER_INTERVAL_SECONDS` | ❌ | `3600` | How often to check for due messages |
| `MAX_SEND_RETRIES` | ❌ | `3` | Max Telegram send attempts before giving up |
| `RETRY_BACKOFF_SECONDS` | ❌ | `5` | Base seconds for exponential back-off |
| `RATE_LIMIT_PER_SECOND` | ❌ | `20` | Max Telegram messages/second |
| `DEFAULT_TIMEZONE` | ❌ | `UTC` | Default timezone for scheduling |
| `FLASK_DEBUG` | ❌ | `false` | Enable Flask debug mode |
| `PORT` | ❌ | `5000` | HTTP port |

---

## Database Schema

### `user_profiles`
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| chat_id | BIGINT | Telegram user/chat ID, unique |
| username | VARCHAR(128) | Optional |
| timezone | VARCHAR(64) | Default: UTC |
| created_at | DATETIME | UTC |
| updated_at | DATETIME | UTC |

### `learning_plans`
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| chat_id | BIGINT | Indexed |
| user_id | INTEGER FK | → user_profiles.id |
| topic | VARCHAR(512) | User's requested topic |
| day | INTEGER | 1–7 |
| content | TEXT | Gemini-generated lesson |
| sent | BOOLEAN | False until delivered |
| send_attempts | INTEGER | For retry tracking |
| scheduled_date | DATETIME | UTC, indexed |
| created_at | DATETIME | UTC |
| sent_at | DATETIME | NULL until delivered |

### `admin_logs`
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| chat_id | BIGINT | |
| event | VARCHAR(64) | e.g. SEND_OK, PLAN_CREATED |
| detail | TEXT | Human-readable context |
| created_at | DATETIME | UTC |

---

## Scaling to Production

The current architecture handles hundreds of active users comfortably. To scale further:

### Replace APScheduler with Celery

```bash
pip install celery redis
```

In `services/scheduler.py`, replace `BackgroundScheduler` with a Celery beat schedule. The `daily_sender.py` logic stays identical — only the trigger mechanism changes.

### Switch to PostgreSQL

```env
DATABASE_URL=postgresql://user:password@host:5432/learning_bot
```

Uncomment `psycopg2-binary` in `requirements.txt`. No code changes needed — SQLAlchemy handles both dialects.

### Add multiple workers

```bash
gunicorn app:app --workers 4 --threads 2
```

Note: APScheduler's `BackgroundScheduler` should run in only **one** worker. Use Celery beat or a dedicated scheduler process when running multiple gunicorn workers.

---

## Troubleshooting

### Webhook not receiving updates

```bash
# Check webhook status
curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo

# Re-register manually
curl -X POST https://api.telegram.org/bot<TOKEN>/setWebhook \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-domain.com/webhook"}'
```

### "Required environment variable not set"

Make sure `.env` exists and all required variables are filled. Run:
```bash
cat .env | grep -v "^#" | grep -v "^$"
```

### Messages not being sent daily

Check the admin_logs table:
```bash
sqlite3 learning_bot.db "SELECT * FROM admin_logs ORDER BY created_at DESC LIMIT 20;"
```

Check scheduler is running:
```bash
# Look for scheduler log lines
grep "Scheduler" bot.log
```

### Gemini returning invalid JSON

The prompt includes explicit instructions to return only JSON. If Gemini wraps the output in markdown fences, `gemini_service._parse_and_validate()` strips them. Check logs for `GeminiError` entries.

### Port already in use

```bash
lsof -i :5000
kill -9 <PID>
```
