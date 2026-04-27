import logging
import os
import sys
import traceback

import requests

from src.fetcher import FeedParseError, fetch_feed, parse_feed
from src.notifier import build_startup_message, send_error, send_message, send_new_events
from src.storage import find_new_events, load_snapshot, save_snapshot


def setup_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        logging.critical("Required environment variable %s is not set", name)
        sys.exit(1)
    return value


def run() -> None:
    logger = logging.getLogger(__name__)

    bot_token = get_required_env("TELEGRAM_BOT_TOKEN")
    chat_id = get_required_env("TELEGRAM_CHAT_ID")
    snapshot_path = os.environ.get("SNAPSHOT_PATH", "/data/snapshot.json")

    try:
        logger.info("Fetching RSS feed...")
        try:
            xml_text = fetch_feed()
        except requests.exceptions.RequestException as exc:
            msg = f"Failed to fetch RSS feed: {exc}"
            logger.error(msg)
            send_error(bot_token, chat_id, msg)
            return

        logger.info("Parsing feed...")
        try:
            current_events = parse_feed(xml_text)
        except FeedParseError as exc:
            msg = f"Failed to parse RSS feed: {exc}"
            logger.error(msg)
            send_error(bot_token, chat_id, msg)
            return

        logger.info("Feed contains %d events", len(current_events))

        snapshot = load_snapshot(snapshot_path)
        is_first_run = len(snapshot) == 0

        if is_first_run:
            logger.info("First run detected — sending startup confirmation")
            startup_msg = build_startup_message(len(current_events))
            with requests.Session() as session:
                send_message(bot_token, chat_id, startup_msg, session)
        else:
            new_events = find_new_events(current_events, snapshot)
            logger.info(
                "Snapshot: %d events. New: %d events.", len(snapshot), len(new_events)
            )
            if new_events:
                send_new_events(bot_token, chat_id, new_events)
            else:
                logger.info("No new events — nothing to send")

        save_snapshot(current_events, snapshot_path)
        logger.info("Snapshot saved (%d events)", len(current_events))

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        logger.error("%s\n%s", msg, traceback.format_exc())
        send_error(get_required_env("TELEGRAM_BOT_TOKEN"), get_required_env("TELEGRAM_CHAT_ID"), msg)


def main() -> None:
    setup_logging()
    run()


if __name__ == "__main__":
    main()
