# DMS Calendar Update Bot

Monitors the [Dallas Makerspace calendar](https://calendar.dallasmakerspace.org) daily and sends new sessions to a Telegram chat. Designed to run on a Raspberry Pi via Docker.

## How it works

Each day the bot fetches the calendar RSS feed, compares it to yesterday's snapshot, and sends a Telegram message listing any newly added events with their links. On first run it sends a confirmation that the bot is up, then starts tracking from that point forward. Errors are also reported to Telegram so you know if something goes wrong.

## Setup

### 1. Prerequisites

- Docker + Docker Compose installed on your Raspberry Pi

### 2. Create a Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts — you'll get a **bot token** like `123456:ABC-DEF...`
3. Add the bot to your target chat/group, then message [@userinfobot](https://t.me/userinfobot) in that chat to get the **chat ID**

### 3. Configure secrets

The Telegram credentials go in a `.env` file (gitignored, never committed):

```bash
cp .env.example .env
```

Edit `.env`:

```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=-100123456789
```

> **Why `.env` and not `config.yml`?**
> `config.yml` is committed to the repo so it shouldn't contain secrets.
> The `.env` file is gitignored and is the standard place for credentials.

### 4. Configure the schedule

Edit `config.yml` to set when the bot runs:

```yaml
schedule:
  hour: 8        # 8 AM
  minute: 0
  timezone: "America/Chicago"

notifications:
  on_error: true
```

### 5. Start the bot

```bash
docker compose up -d
```

That's it. The container runs as a persistent daemon with an internal cron job — no host crontab setup needed. You should receive a Telegram message shortly: *"✅ DMS Calendar Bot is running! Found N events..."*

To update the schedule, edit `config.yml` and restart:

```bash
docker compose restart
```

To view logs:

```bash
docker compose logs -f
```

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run tests:

```bash
pytest tests/ -v
```

Run the bot locally (without Docker, fires immediately):

```bash
cp .env.example .env  # fill in your credentials
SNAPSHOT_PATH=./data/snapshot.json python -m src.main
```

## Project structure

```
src/
  fetcher.py    — fetch and parse the RSS feed
  storage.py    — load/save the event snapshot (JSON)
  notifier.py   — format and send Telegram messages
  config.py     — load config.yml with defaults
  main.py       — orchestrates the pipeline
tests/          — 55 tests covering all modules
data/           — snapshot lives here (Docker volume, gitignored)
config.yml      — schedule and notification settings
entrypoint.sh   — builds the crontab from config.yml and starts supercronic
docker-compose.yml
Dockerfile
```

## Simulating a new event (testing)

To verify Telegram notifications work without waiting a day:

```bash
# Remove one event from the snapshot to simulate it being "new"
python3 -c "
import json
with open('data/snapshot.json') as f: s = json.load(f)
del s[list(s.keys())[0]]
with open('data/snapshot.json', 'w') as f: json.dump(s, f, indent=2)
"

# Trigger a manual run inside the running container
docker compose exec app python -m src.main
```

You should receive a Telegram message with one new event.
