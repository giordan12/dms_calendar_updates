import logging
import os

import yaml
from typesafe_sdk import Noul, TypeSafeClient

logger = logging.getLogger(__name__)

QUESTION_ID = "recommend_class"
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
    data.setdefault("class_category", "Class")
    data.setdefault("max_description_chars", 1500)
    return data


def select_classes(events: list[dict], category: str) -> list[dict]:
    return [e for e in events if category in e.get("categories", [])]


def build_class_state(event: dict, max_description_chars: int = 1500) -> dict:
    return {
        "title": event.get("title", "").strip(),
        "categories": list(event.get("categories", [])),
        "description": (event.get("description") or "").strip()[
            :max_description_chars
        ],
    }


def build_noul_question(config: dict) -> Noul:
    return Noul(
        instructions=config["instructions"].strip(),
        criteria=config.get("criteria"),
    )


def score_class(event: dict, config: dict, client: TypeSafeClient) -> float:
    response = client.system_one(
        state=build_class_state(event, config["max_description_chars"]),
        questions={QUESTION_ID: build_noul_question(config)},
        model=config["model"],
    )
    return response.nouls[QUESTION_ID].noul


def recommend_classes(
    new_events: list[dict], config: dict, client: TypeSafeClient
) -> list[dict]:
    recommended = []
    for event in select_classes(new_events, config["class_category"]):
        try:
            probability = score_class(event, config, client)
        except Exception as exc:
            logger.warning("Could not score class %r: %s", event.get("title"), exc)
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
