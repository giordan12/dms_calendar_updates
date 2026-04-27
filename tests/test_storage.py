import json
import os

import pytest

from src.storage import find_new_events, load_snapshot, save_snapshot

SAMPLE_EVENTS = [
    {"guid": "http://example.com/events/view/1", "event_id": "1", "title": "Event A", "link": "http://example.com/events/view/1", "when": "Mon Apr 27 10am", "pub_date": "", "categories": []},
    {"guid": "http://example.com/events/view/2", "event_id": "2", "title": "Event B", "link": "http://example.com/events/view/2", "when": "Tue Apr 28 2pm", "pub_date": "", "categories": []},
    {"guid": "http://example.com/events/view/3", "event_id": "3", "title": "Event C", "link": "http://example.com/events/view/3", "when": "", "pub_date": "", "categories": ["Class"]},
]


class TestLoadSnapshot:
    def test_missing_file_returns_empty(self, tmp_path):
        result = load_snapshot(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_valid_snapshot_loads(self, tmp_path):
        path = tmp_path / "snapshot.json"
        data = {e["guid"]: e for e in SAMPLE_EVENTS}
        path.write_text(json.dumps(data), encoding="utf-8")
        result = load_snapshot(str(path))
        assert len(result) == 3
        assert "http://example.com/events/view/1" in result

    def test_corrupted_json_returns_empty(self, tmp_path):
        path = tmp_path / "snapshot.json"
        path.write_text("{ this is not valid json }", encoding="utf-8")
        result = load_snapshot(str(path))
        assert result == {}


class TestSaveSnapshot:
    def test_creates_file_with_guids_as_keys(self, tmp_path):
        path = str(tmp_path / "snapshot.json")
        save_snapshot(SAMPLE_EVENTS, path)
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert set(data.keys()) == {e["guid"] for e in SAMPLE_EVENTS}

    def test_no_tmp_file_lingers(self, tmp_path):
        path = str(tmp_path / "snapshot.json")
        save_snapshot(SAMPLE_EVENTS, path)
        assert not os.path.exists(path + ".tmp")

    def test_round_trips_correctly(self, tmp_path):
        path = str(tmp_path / "snapshot.json")
        save_snapshot(SAMPLE_EVENTS, path)
        result = load_snapshot(path)
        assert len(result) == 3
        assert result["http://example.com/events/view/2"]["title"] == "Event B"

    def test_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "nested" / "deep" / "snapshot.json")
        save_snapshot(SAMPLE_EVENTS, path)
        assert os.path.exists(path)

    def test_overwrites_existing(self, tmp_path):
        path = str(tmp_path / "snapshot.json")
        save_snapshot(SAMPLE_EVENTS[:1], path)
        save_snapshot(SAMPLE_EVENTS, path)
        result = load_snapshot(path)
        assert len(result) == 3


class TestFindNewEvents:
    def test_empty_snapshot_returns_all(self):
        result = find_new_events(SAMPLE_EVENTS, {})
        assert result == SAMPLE_EVENTS

    def test_no_new_events(self):
        snapshot = {e["guid"]: e for e in SAMPLE_EVENTS}
        result = find_new_events(SAMPLE_EVENTS, snapshot)
        assert result == []

    def test_returns_only_new(self):
        snapshot = {e["guid"]: e for e in SAMPLE_EVENTS[:2]}
        result = find_new_events(SAMPLE_EVENTS, snapshot)
        assert len(result) == 1
        assert result[0]["guid"] == "http://example.com/events/view/3"

    def test_preserves_order(self):
        snapshot = {SAMPLE_EVENTS[1]["guid"]: SAMPLE_EVENTS[1]}
        result = find_new_events(SAMPLE_EVENTS, snapshot)
        guids = [e["guid"] for e in result]
        assert guids == [
            "http://example.com/events/view/1",
            "http://example.com/events/view/3",
        ]
