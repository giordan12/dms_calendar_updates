import json
import logging
import os
from pathlib import Path

DEFAULT_SNAPSHOT_PATH = "/data/snapshot.json"

logger = logging.getLogger(__name__)


def load_snapshot(path: str = DEFAULT_SNAPSHOT_PATH) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.warning("Snapshot at %s is corrupted — treating as first run", path)
        return {}


def save_snapshot(events: list[dict], path: str = DEFAULT_SNAPSHOT_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    snapshot = {event["guid"]: event for event in events}
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def find_new_events(
    current: list[dict], snapshot: dict[str, dict]
) -> list[dict]:
    known_guids = set(snapshot.keys())
    return [e for e in current if e["guid"] not in known_guids]
