import logging
import os

import requests
import yaml

logger = logging.getLogger(__name__)

JEV_URL = "https://api.typesafe.ai/v1/systemone"
QUESTION_ID = "recommend_class"


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


def build_noul_question(config: dict) -> dict:
    question = {"type": "noul", "instructions": config["instructions"].strip()}
    if config.get("criteria"):
        question["criteria"] = config["criteria"]
    return question


def parse_noul(body: dict) -> float:
    try:
        value = body["answers"][QUESTION_ID]["noul"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"No noul answer in Jev response: {body!r}") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Invalid noul value in Jev response: {value!r}")
    if not 0 <= value <= 1:
        raise ValueError(f"noul out of range [0, 1]: {value}")
    return float(value)


def score_class(
    event: dict, config: dict, api_key: str, session: requests.Session
) -> float:
    payload = {
        "model": config["model"],
        "state": build_class_state(event, config["max_description_chars"]),
        "questions": {QUESTION_ID: build_noul_question(config)},
    }
    response = session.post(
        JEV_URL,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    response.raise_for_status()
    return parse_noul(response.json())


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
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        logger.info("TYPESAFE_API_KEY not set — skipping recommendations")
        return []
    try:
        return recommend_classes(new_events, config, api_key)
    except Exception as exc:
        logger.warning("Recommendation step failed: %s", exc)
        return []
