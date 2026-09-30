"""Manual live check of the Jev integration (not part of the pytest suite).

Samples some classes, scores them with Jev, and prints the recommended ones to
stdout instead of sending them to Telegram.

By default the classes come from a pre-stored JSON file, so repeated runs don't
query the DMS site. Pass --live to pull the current classes from the site
instead; that also refreshes the stored file.

    TYPESAFE_API_KEY=... python -m scripts.sample_recommendations [--live] [--count 20] [--seed 1]
"""

import argparse
import json
import logging
import os
import random
import sys
from pathlib import Path

from typesafe_sdk import TypeSafeClient

from src.fetcher import fetch_feed, parse_feed
from src.recommender import (
    REQUEST_TIMEOUT_SECONDS,
    RecommenderConfigError,
    load_recommender_config,
    recommend_classes,
    select_classes,
)

STORED_CLASSES_PATH = Path(__file__).with_name("stored_classes.json")


def load_stored_classes(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_stored_classes(classes: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(classes, f, indent=2, ensure_ascii=False)
        f.write("\n")


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
    parser.add_argument(
        "--live",
        "--livemode",
        action="store_true",
        help="pull classes from the DMS site (and refresh the stored file) "
        "instead of loading the stored ones",
    )
    parser.add_argument("--count", type=int, default=20, help="classes to sample")
    parser.add_argument("--seed", type=int, default=None, help="seed for repeatable samples")
    parser.add_argument("--config", default="recommendations.yml")
    parser.add_argument(
        "--classes-file", type=Path, default=STORED_CLASSES_PATH, help="stored classes JSON"
    )
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

    if args.live:
        events = select_classes(parse_feed(fetch_feed()))
        save_stored_classes(events, args.classes_file)
        print(f"Pulled {len(events)} classes from the site, saved to {args.classes_file}")
    else:
        try:
            events = load_stored_classes(args.classes_file)
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"Cannot load stored classes from {args.classes_file}: {exc}\n"
                "Run with --live to pull them from the site.",
                file=sys.stderr,
            )
            return 1
        print(f"Loaded {len(events)} stored classes from {args.classes_file}")

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
