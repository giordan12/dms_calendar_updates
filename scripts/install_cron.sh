#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$PROJECT_DIR/config.yml"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "Error: config.yml not found at $CONFIG_FILE"
  exit 1
fi

HOUR=$(python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG_FILE')); print(c['schedule']['hour'])")
MINUTE=$(python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG_FILE')); print(c['schedule']['minute'])")
TZ=$(python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG_FILE')); print(c['schedule']['timezone'])")

echo "Setting timezone to $TZ..."
sudo timedatectl set-timezone "$TZ"

CRON_LINE="$MINUTE $HOUR * * * cd $PROJECT_DIR && /usr/bin/docker compose run --rm app >> /var/log/dms-bot.log 2>&1"

echo "Installing crontab entry:"
echo "  $CRON_LINE"

# Remove any existing dms_calendar_updates cron entry, then add the new one
(crontab -l 2>/dev/null | grep -v "dms_calendar_updates"; echo "$CRON_LINE") | crontab -

echo "Done. Verify with: crontab -l"
