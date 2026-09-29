import json
from unittest.mock import MagicMock, patch

import pytest
import requests
import yaml

from src.recommender import (
    ANTHROPIC_URL,
    RecommenderConfigError,
    build_class_prompt,
    get_recommendations,
    load_recommender_config,
    parse_yes_probability,
    recommend_classes,
    score_class,
    select_classes,
)

CONFIG = {
    "enabled": True,
    "model": "test-model",
    "max_tokens": 50,
    "threshold": 0.6,
    "class_category": "Class",
    "max_description_chars": 20,
    "instructions": "Be a judge.",
}


def make_event(title="Laser Basics", categories=("Class",), description="Learn lasers"):
    return {
        "title": title,
        "link": f"http://example.com/{title}",
        "when": "Mon 10am",
        "description": description,
        "categories": list(categories),
    }


def api_response(probability):
    resp = MagicMock()
    resp.json.return_value = {
        "content": [
            {"type": "text", "text": json.dumps({"yes_probability": probability})}
        ]
    }
    return resp


class TestLoadConfig:
    def test_tracked_config_is_valid(self):
        config = load_recommender_config("recommendations.yml")
        assert config["instructions"].strip()
        assert 0 < config["threshold"] < 1
        assert config["model"]

    def test_defaults_applied(self, tmp_path):
        path = tmp_path / "r.yml"
        path.write_text(yaml.dump({"model": "m", "instructions": "i", "threshold": 0.5}))
        config = load_recommender_config(str(path))
        assert config["enabled"] is True
        assert config["class_category"] == "Class"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RecommenderConfigError):
            load_recommender_config(str(tmp_path / "nope.yml"))

    def test_missing_key_raises(self, tmp_path):
        path = tmp_path / "r.yml"
        path.write_text(yaml.dump({"model": "m"}))
        with pytest.raises(RecommenderConfigError, match="instructions"):
            load_recommender_config(str(path))

    def test_invalid_yaml_raises(self, tmp_path):
        path = tmp_path / "r.yml"
        path.write_text("a: [unclosed")
        with pytest.raises(RecommenderConfigError):
            load_recommender_config(str(path))


class TestSelectClasses:
    def test_keeps_only_class_category(self):
        events = [make_event("A"), make_event("B", categories=["Event"])]
        assert [e["title"] for e in select_classes(events, "Class")] == ["A"]

    def test_handles_missing_categories(self):
        assert select_classes([{"title": "x"}], "Class") == []


class TestBuildClassPrompt:
    def test_includes_title_description_categories(self):
        prompt = build_class_prompt(make_event(categories=["Class", "Laser"]))
        assert "Laser Basics" in prompt
        assert "Learn lasers" in prompt
        assert "Class, Laser" in prompt

    def test_truncates_description(self):
        prompt = build_class_prompt(make_event(description="x" * 100), 10)
        assert "x" * 10 in prompt
        assert "x" * 11 not in prompt

    def test_empty_description_placeholder(self):
        assert "(none)" in build_class_prompt(make_event(description=""))


class TestParseYesProbability:
    def test_plain_json(self):
        assert parse_yes_probability('{"yes_probability": 0.75}') == 0.75

    def test_json_with_surrounding_text(self):
        assert parse_yes_probability('Sure: {"yes_probability": 0.9} ok') == 0.9

    def test_integer_bounds_accepted(self):
        assert parse_yes_probability('{"yes_probability": 1}') == 1.0
        assert parse_yes_probability('{"yes_probability": 0}') == 0.0

    @pytest.mark.parametrize(
        "text",
        [
            "no json here",
            '{"other": 1}',
            '{"yes_probability": "high"}',
            '{"yes_probability": true}',
            '{"yes_probability": 1.5}',
            '{"yes_probability": -0.1}',
        ],
    )
    def test_invalid_raises(self, text):
        with pytest.raises((ValueError, json.JSONDecodeError)):
            parse_yes_probability(text)


class TestScoreClass:
    def test_sends_expected_request(self):
        session = MagicMock()
        session.post.return_value = api_response(0.8)
        result = score_class(make_event(), CONFIG, "key123", session)
        assert result == 0.8
        args, kwargs = session.post.call_args
        assert args[0] == ANTHROPIC_URL
        assert kwargs["headers"]["x-api-key"] == "key123"
        assert kwargs["json"]["model"] == "test-model"
        assert kwargs["json"]["system"] == "Be a judge."
        assert kwargs["json"]["max_tokens"] == 50
        assert "Laser Basics" in kwargs["json"]["messages"][0]["content"]

    def test_http_error_propagates(self):
        session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
        session.post.return_value = resp
        with pytest.raises(requests.exceptions.HTTPError):
            score_class(make_event(), CONFIG, "k", session)


class TestRecommendClasses:
    def _run(self, events, probabilities):
        session = MagicMock()
        session.post.side_effect = probabilities
        with patch("src.recommender.requests.Session") as cls:
            cls.return_value.__enter__.return_value = session
            result = recommend_classes(events, CONFIG, "k")
        return result, session

    def test_only_above_threshold_recommended(self):
        events = [make_event("A"), make_event("B"), make_event("C")]
        result, _ = self._run(
            events, [api_response(0.61), api_response(0.6), api_response(0.2)]
        )
        assert [e["title"] for e in result] == ["A"]
        assert result[0]["yes_probability"] == 0.61

    def test_threshold_is_strict(self):
        result, _ = self._run([make_event()], [api_response(0.6)])
        assert result == []

    def test_non_classes_not_sent_to_llm(self):
        events = [make_event("A"), make_event("Tour", categories=["Event"])]
        _, session = self._run(events, [api_response(0.9)])
        assert session.post.call_count == 1

    def test_one_call_per_class(self):
        events = [make_event(str(i)) for i in range(4)]
        _, session = self._run(events, [api_response(0.1)] * 4)
        assert session.post.call_count == 4

    def test_failed_class_skipped_others_continue(self):
        events = [make_event("A"), make_event("B")]
        result, _ = self._run(
            events, [requests.exceptions.ConnectionError("x"), api_response(0.9)]
        )
        assert [e["title"] for e in result] == ["B"]

    def test_malformed_response_skipped(self):
        bad = MagicMock()
        bad.json.return_value = {"content": [{"type": "text", "text": "maybe?"}]}
        result, _ = self._run([make_event()], [bad])
        assert result == []


class TestGetRecommendations:
    def test_no_api_key_skips(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch("src.recommender.recommend_classes") as rc:
            assert get_recommendations([make_event()], "recommendations.yml") == []
        rc.assert_not_called()

    def test_disabled_skips(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        path = tmp_path / "r.yml"
        path.write_text(
            yaml.dump(
                {"model": "m", "instructions": "i", "threshold": 0.5, "enabled": False}
            )
        )
        with patch("src.recommender.recommend_classes") as rc:
            assert get_recommendations([make_event()], str(path)) == []
        rc.assert_not_called()

    def test_bad_config_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        assert get_recommendations([make_event()], str(tmp_path / "nope.yml")) == []

    def test_uses_env_key_and_returns_results(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
        with patch("src.recommender.recommend_classes", return_value=["r"]) as rc:
            assert get_recommendations([make_event()], "recommendations.yml") == ["r"]
        assert rc.call_args[0][2] == "secret"

    def test_unexpected_failure_returns_empty(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        with patch("src.recommender.recommend_classes", side_effect=RuntimeError):
            assert get_recommendations([make_event()], "recommendations.yml") == []
