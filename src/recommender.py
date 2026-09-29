import logging
import os

import yaml
from typesafe_sdk import Noul, TypeSafeClient

logger = logging.getLogger(__name__)

CLASS_CATEGORY = "Class"
REQUEST_TIMEOUT_SECONDS = 30


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
    data.setdefault("max_description_chars", 1500)
    data.setdefault("batch_size", 20)
    if data["batch_size"] < 1:
        raise RecommenderConfigError(f"{path}: batch_size must be at least 1")
    return data


def select_classes(events: list[dict]) -> list[dict]:
    return [e for e in events if CLASS_CATEGORY in e.get("categories", [])]


def build_class_state(event: dict, max_description_chars: int = 1500) -> dict:
    return {
        "title": event.get("title", "").strip(),
        "categories": list(event.get("categories", [])),
        "description": (event.get("description") or "").strip()[
            :max_description_chars
        ],
    }


def build_noul_question(config: dict, class_key: str) -> Noul:
    instructions = (
        f"{config['instructions'].strip()}\n\n"
        f'Evaluate only the class with id "{class_key}" in the state.'
    )
    return Noul(instructions=instructions, criteria=config.get("criteria"))


def score_batch(
    events: list[dict], config: dict, client: TypeSafeClient
) -> list[float | None]:
    """Score events in one request: shared state, one noul question per class.

    Returns one probability per event, or None where Jev gave no answer.
    """
    keys = [f"class_{i}" for i in range(len(events))]
    state = {
        "classes": {
            key: build_class_state(event, config["max_description_chars"])
            for key, event in zip(keys, events)
        }
    }
    questions = {key: build_noul_question(config, key) for key in keys}
    response = client.system_one(
        state=state, questions=questions, model=config["model"]
    )
    scores = []
    for key, event in zip(keys, events):
        answer = response.nouls.get(key)
        if answer is None:
            logger.warning("No answer from Jev for class %r", event.get("title"))
        scores.append(None if answer is None else answer.noul)
    return scores


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def recommend_classes(
    new_events: list[dict], config: dict, client: TypeSafeClient
) -> list[dict]:
    recommended = []
    classes = select_classes(new_events)
    for batch in _chunks(classes, config["batch_size"]):
        try:
            scores = score_batch(batch, config, client)
        except Exception as exc:
            logger.warning("Could not score batch of %d classes: %s", len(batch), exc)
            continue
        for event, probability in zip(batch, scores):
            if probability is None:
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
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        logger.info("TYPESAFE_API_KEY not set — skipping recommendations")
        return []
    try:
        with TypeSafeClient(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS) as client:
            return recommend_classes(new_events, config, client)
    except Exception as exc:
        logger.warning("Recommendation step failed: %s", exc)
        return []
