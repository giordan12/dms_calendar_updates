import json
import logging
import os
import re

import requests
import yaml

logger = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

_JSON_OBJECT = re.compile(r"\{.*?\}", re.DOTALL)


class RecommenderConfigError(Exception):
    pass


def load_recommender_config(path: str = "recommendations.yml") -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RecommenderConfigError(f"Cannot load {path}: {exc}") from exc
    for key in ("model", "instructions", "threshold"):
        if key not in data:
            raise RecommenderConfigError(f"{path} is missing required key '{key}'")
    data.setdefault("enabled", True)
    data.setdefault("max_tokens", 100)
    data.setdefault("class_category", "Class")
    data.setdefault("max_description_chars", 1500)
    return data


def select_classes(events: list[dict], category: str) -> list[dict]:
    return [e for e in events if category in e.get("categories", [])]


def build_class_prompt(event: dict, max_description_chars: int = 1500) -> str:
    description = (event.get("description") or "").strip()[:max_description_chars]
    categories = ", ".join(event.get("categories", [])) or "(none)"
    return (
        f"Title: {event.get('title', '').strip()}\n"
        f"Categories: {categories}\n"
        f"Description: {description or '(none)'}"
    )


def parse_yes_probability(text: str) -> float:
    match = _JSON_OBJECT.search(text)
    if not match:
        raise ValueError(f"No JSON object in model response: {text!r}")
    value = json.loads(match.group(0)).get("yes_probability")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Invalid yes_probability in model response: {text!r}")
    if not 0 <= value <= 1:
        raise ValueError(f"yes_probability out of range [0, 1]: {value}")
    return float(value)


def score_class(
    event: dict, config: dict, api_key: str, session: requests.Session
) -> float:
    payload = {
        "model": config["model"],
        "max_tokens": config["max_tokens"],
        "system": config["instructions"],
        "messages": [
            {
                "role": "user",
                "content": build_class_prompt(
                    event, config["max_description_chars"]
                ),
            }
        ],
    }
    response = session.post(
        ANTHROPIC_URL,
        json=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        timeout=30,
    )
    response.raise_for_status()
    blocks = response.json().get("content", [])
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    return parse_yes_probability(text)


def recommend_classes(
    new_events: list[dict], config: dict, api_key: str
) -> list[dict]:
    classes = select_classes(new_events, config["class_category"])
    recommended = []
    with requests.Session() as session:
        for event in classes:
            try:
                probability = score_class(event, config, api_key, session)
            except Exception as exc:
                logger.warning(
                    "Could not score class %r: %s", event.get("title"), exc
                )
                continue
            logger.info("Class %r scored %.2f", event.get("title"), probability)
            if probability > config["threshold"]:
                recommended.append({**event, "yes_probability": probability})
    return recommended


def get_recommendations(
    new_events: list[dict], config_path: str = "recommendations.yml"
) -> list[dict]:
    """Return recommended classes; never raises so it can't block the main flow."""
    try:
        config = load_recommender_config(config_path)
    except RecommenderConfigError as exc:
        logger.warning("Skipping recommendations: %s", exc)
        return []
    if not config["enabled"]:
        return []
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set — skipping recommendations")
        return []
    try:
        return recommend_classes(new_events, config, api_key)
    except Exception as exc:
        logger.warning("Recommendation step failed: %s", exc)
        return []
