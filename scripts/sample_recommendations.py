"""Manual live check of the Jev integration (not part of the pytest suite).

Loads the classes from the real DMS schedule, samples some, scores them with Jev,
and prints the recommended ones to stdout instead of sending them to Telegram.

    TYPESAFE_API_KEY=... python -m scripts.sample_recommendations [--count 20] [--seed 1]
"""

import argparse
import logging
import os
import random
import sys

from typesafe_sdk import TypeSafeClient

from src.fetcher import fetch_feed, parse_feed
from src.recommender import (
    REQUEST_TIMEOUT_SECONDS,
    RecommenderConfigError,
    load_recommender_config,
    recommend_classes,
    select_classes,
)


def sample_classes(events: list[dict], count: int, seed: int | None = None) -> list[dict]:
    classes = select_classes(events)
    return random.Random(seed).sample(classes, min(count, len(classes)))


def format_recommendation(event: dict) -> str:
    line = f"  {event['yes_probability']:.2f}  {event.get('title', '').strip()}"
    if event.get("when"):
        line += f" — {event['when']}"
    return f"{line}\n        {event.get('link', '')}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=20, help="classes to sample")
    parser.add_argument("--seed", type=int, default=None, help="seed for repeatable samples")
    parser.add_argument("--config", default="recommendations.yml")
    args = parser.parse_args(argv)

    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        print("TYPESAFE_API_KEY is not set", file=sys.stderr)
        return 1
    try:
        config = load_recommender_config(args.config)
    except RecommenderConfigError as exc:
        print(exc, file=sys.stderr)
        return 1

    # Per-class scores and any batch failures are logged by the recommender.
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")

    events = parse_feed(fetch_feed())
    total_classes = len(select_classes(events))
    sample = sample_classes(events, args.count, args.seed)
    print(f"Sampled {len(sample)} of {total_classes} classes with {config['model']}\n")
    if not sample:
        return 0

    with TypeSafeClient(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS) as client:
        recommended = recommend_classes(sample, config, client)

    print(f"\nRecommended (noul > {config['threshold']}): {len(recommended)} of {len(sample)}")
    for event in sorted(recommended, key=lambda e: e["yes_probability"], reverse=True):
        print(format_recommendation(event))
    return 0


if __name__ == "__main__":
    sys.exit(main())
