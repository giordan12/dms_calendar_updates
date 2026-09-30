from unittest.mock import patch

import pytest

from src import main

OLD = {"guid": "old", "title": "Old", "categories": ["Class"]}
NEW = {"guid": "new", "title": "New Class", "categories": ["Class"]}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setenv("SNAPSHOT_PATH", str(tmp_path / "snap.json"))


def run_with(snapshot, current, recommended):
    with patch("src.main.fetch_feed", return_value="<xml/>"), \
         patch("src.main.parse_feed", return_value=current), \
         patch("src.main.load_snapshot", return_value=snapshot), \
         patch("src.main.save_snapshot") as save, \
         patch("src.main.send_new_events") as send_new, \
         patch("src.main.get_recommendations", return_value=recommended) as rec, \
         patch("src.main.send_recommendations") as send_rec, \
         patch("src.main.send_message"), \
         patch("src.main.send_error") as send_err:
        main.run()
    return save, send_new, rec, send_rec, send_err


def test_new_events_trigger_recommendations(env):
    recommended = [{**NEW, "yes_probability": 0.9}]
    save, send_new, rec, send_rec, _ = run_with({"old": OLD}, [OLD, NEW], recommended)
    send_new.assert_called_once()
    rec.assert_called_once_with([NEW])
    send_rec.assert_called_once_with("t", "c", recommended)
    save.assert_called_once()


def test_recommendations_sent_after_new_events(env):
    order = []
    with patch("src.main.fetch_feed", return_value=""), \
         patch("src.main.parse_feed", return_value=[OLD, NEW]), \
         patch("src.main.load_snapshot", return_value={"old": OLD}), \
         patch("src.main.save_snapshot"), \
         patch("src.main.send_new_events", side_effect=lambda *a: order.append("new")), \
         patch("src.main.get_recommendations", return_value=[]), \
         patch("src.main.send_recommendations", side_effect=lambda *a: order.append("rec")):
        main.run()
    assert order == ["new", "rec"]


def test_no_new_events_no_recommendations(env):
    _, send_new, rec, send_rec, _ = run_with({"old": OLD}, [OLD], [])
    send_new.assert_not_called()
    rec.assert_not_called()
    send_rec.assert_not_called()


def test_first_run_no_recommendations(env):
    _, _, rec, send_rec, _ = run_with({}, [OLD, NEW], [])
    rec.assert_not_called()
    send_rec.assert_not_called()
