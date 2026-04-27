#!/bin/sh
set -e

# Read schedule from config.yml
HOUR=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yml')); print(c['schedule']['hour'])")
MINUTE=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yml')); print(c['schedule']['minute'])")

CRONTAB="/tmp/crontab"
echo "$MINUTE $HOUR * * * python -m src.main" > "$CRONTAB"

echo "Scheduler started — bot will run daily at ${HOUR}:$(printf '%02d' $MINUTE)"

exec supercronic "$CRONTAB"
