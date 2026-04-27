import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from src.config import load_config
from src.main import run, setup_logging


def start() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    config = load_config()
    hour = config["schedule"]["hour"]
    minute = config["schedule"]["minute"]
    timezone = config["schedule"]["timezone"]

    logger.info("Starting scheduler — job will run daily at %02d:%02d %s", hour, minute, timezone)

    # Run once immediately on startup so first-run confirmation is sent right away
    logger.info("Running immediately on startup...")
    run()

    scheduler = BlockingScheduler(timezone=timezone)
    scheduler.add_job(run, "cron", hour=hour, minute=minute)
    scheduler.start()


if __name__ == "__main__":
    start()
