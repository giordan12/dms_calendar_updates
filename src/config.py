import logging
import os

import yaml

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "schedule": {
        "hour": 8,
        "minute": 0,
        "timezone": "America/Chicago",
    },
    "notifications": {
        "on_error": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str = "config.yml") -> dict:
    if not os.path.exists(path):
        logger.warning("Config file %s not found — using defaults", path)
        return _deep_merge({}, _DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return _deep_merge(_DEFAULTS, data)
    except yaml.YAMLError as exc:
        logger.warning("Invalid YAML in %s: %s — using defaults", path, exc)
        return _deep_merge({}, _DEFAULTS)
