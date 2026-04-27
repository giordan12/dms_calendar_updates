# DMS Calendar Update Bot

Monitors the [Dallas Makerspace calendar](https://calendar.dallasmakerspace.org) daily and sends new sessions to a Telegram chat. Designed to run on a Raspberry Pi via Docker and host cron.

## How it works

Each day the bot fetches the calendar RSS feed, compares it to yesterday's snapshot, and sends a Telegram message listing any newly added events with their links. On first run it sends a confirmation that the bot is up, then starts tracking from that point forward. Errors are also reported to Telegram so you know if something goes wrong.

## Setup

### 1. Prerequisites

- Docker + Docker Compose
- A Telegram bot token and chat ID (see below)

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

### 5. First run

```bash
# Create the data directory
mkdir -p data

# Run the bot once
docker compose run --rm app
```

You should receive a Telegram message: *"✅ DMS Calendar Bot is running! Found N events..."*

### 6. Set up the daily cron job (Raspberry Pi)

```bash
chmod +x scripts/install_cron.sh
./scripts/install_cron.sh
```

This reads the time from `config.yml`, sets the system timezone, and installs the crontab entry. To update the schedule, edit `config.yml` and re-run the script.

Verify it was installed:

```bash
crontab -l
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

Run locally (without Docker):

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
docker-compose.yml
Dockerfile
scripts/
  install_cron.sh — installs the host cron job from config.yml
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

docker compose run --rm app
```

You should receive a Telegram message with one new event.
