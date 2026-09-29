from unittest.mock import MagicMock, patch

import pytest
import requests
import yaml

from src.recommender import (
    JEV_URL,
    QUESTION_ID,
    RecommenderConfigError,
    build_class_state,
    build_noul_question,
    get_recommendations,
    load_recommender_config,
    parse_noul,
    recommend_classes,
    score_class,
    select_classes,
)

CONFIG = {
    "enabled": True,
    "model": "jev-test",
    "threshold": 0.6,
    "class_category": "Class",
    "max_description_chars": 20,
    "instructions": "Recommend this?\n",
    "criteria": {"true": "good", "false": "bad"},
}


def make_event(title="Laser Basics", categories=("Class",), description="Learn lasers"):
    return {
        "title": title,
        "link": f"http://example.com/{title}",
        "when": "Mon 10am",
        "description": description,
        "categories": list(categories),
    }


def jev_body(noul):
    return {
        "model": "jev-1.13.0",
        "answers": {QUESTION_ID: {"type": "noul", "noul": noul}},
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def jev_response(noul):
    resp = MagicMock()
    resp.json.return_value = jev_body(noul)
    return resp


class TestLoadConfig:
    def test_tracked_config_is_valid(self):
        config = load_recommender_config("recommendations.yml")
        assert config["instructions"].strip()
        assert 0 < config["threshold"] < 1
        assert config["model"].startswith("jev")

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


class TestBuildClassState:
    def test_includes_title_description_categories(self):
        state = build_class_state(make_event(categories=["Class", "Laser"]))
        assert state == {
            "title": "Laser Basics",
            "categories": ["Class", "Laser"],
            "description": "Learn lasers",
        }

    def test_truncates_description(self):
        state = build_class_state(make_event(description="x" * 100), 10)
        assert state["description"] == "x" * 10

    def test_missing_description(self):
        event = make_event()
        del event["description"]
        assert build_class_state(event)["description"] == ""


class TestBuildNoulQuestion:
    def test_with_criteria(self):
        assert build_noul_question(CONFIG) == {
            "type": "noul",
            "instructions": "Recommend this?",
            "criteria": {"true": "good", "false": "bad"},
        }

    def test_without_criteria(self):
        config = {k: v for k, v in CONFIG.items() if k != "criteria"}
        assert "criteria" not in build_noul_question(config)


class TestParseNoul:
    def test_valid(self):
        assert parse_noul(jev_body(0.75)) == 0.75

    def test_integer_bounds_accepted(self):
        assert parse_noul(jev_body(1)) == 1.0
        assert parse_noul(jev_body(0)) == 0.0

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"answers": {}},
            {"answers": {QUESTION_ID: {"type": "noul"}}},
            {"answers": {QUESTION_ID: {"noul": "high"}}},
            {"answers": {QUESTION_ID: {"noul": True}}},
            {"answers": {QUESTION_ID: {"noul": 1.5}}},
            {"answers": {QUESTION_ID: {"noul": -0.1}}},
            {"answers": None},
        ],
    )
    def test_invalid_raises(self, body):
        with pytest.raises(ValueError):
            parse_noul(body)


class TestScoreClass:
    def test_sends_expected_request(self):
        session = MagicMock()
        session.post.return_value = jev_response(0.8)
        result = score_class(make_event(), CONFIG, "key123", session)
        assert result == 0.8
        args, kwargs = session.post.call_args
        assert args[0] == JEV_URL
        assert kwargs["headers"]["Authorization"] == "Bearer key123"
        body = kwargs["json"]
        assert body["model"] == "jev-test"
        assert body["state"]["title"] == "Laser Basics"
        assert body["questions"][QUESTION_ID]["type"] == "noul"
        assert body["questions"][QUESTION_ID]["instructions"] == "Recommend this?"

    def test_http_error_propagates(self):
        session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
        session.post.return_value = resp
        with pytest.raises(requests.exceptions.HTTPError):
            score_class(make_event(), CONFIG, "k", session)


class TestRecommendClasses:
    def _run(self, events, responses):
        session = MagicMock()
        session.post.side_effect = responses
        with patch("src.recommender.requests.Session") as cls:
            cls.return_value.__enter__.return_value = session
            result = recommend_classes(events, CONFIG, "k")
        return result, session

    def test_only_above_threshold_recommended(self):
        events = [make_event("A"), make_event("B"), make_event("C")]
        result, _ = self._run(
            events, [jev_response(0.61), jev_response(0.6), jev_response(0.2)]
        )
        assert [e["title"] for e in result] == ["A"]
        assert result[0]["yes_probability"] == 0.61

    def test_threshold_is_strict(self):
        result, _ = self._run([make_event()], [jev_response(0.6)])
        assert result == []

    def test_non_classes_not_sent_to_jev(self):
        events = [make_event("A"), make_event("Tour", categories=["Event"])]
        _, session = self._run(events, [jev_response(0.9)])
        assert session.post.call_count == 1

    def test_one_call_per_class(self):
        events = [make_event(str(i)) for i in range(4)]
        _, session = self._run(events, [jev_response(0.1)] * 4)
        assert session.post.call_count == 4

    def test_failed_class_skipped_others_continue(self):
        events = [make_event("A"), make_event("B")]
        result, _ = self._run(
            events, [requests.exceptions.ConnectionError("x"), jev_response(0.9)]
        )
        assert [e["title"] for e in result] == ["B"]

    def test_malformed_response_skipped(self):
        bad = MagicMock()
        bad.json.return_value = {"answers": {}}
        result, _ = self._run([make_event()], [bad])
        assert result == []


class TestGetRecommendations:
    def test_no_api_key_skips(self, monkeypatch):
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        with patch("src.recommender.recommend_classes") as rc:
            assert get_recommendations([make_event()], "recommendations.yml") == []
        rc.assert_not_called()

    def test_disabled_skips(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
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
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
        assert get_recommendations([make_event()], str(tmp_path / "nope.yml")) == []

    def test_uses_env_key_and_returns_results(self, monkeypatch):
        monkeypatch.setenv("TYPESAFE_API_KEY", "secret")
        with patch("src.recommender.recommend_classes", return_value=["r"]) as rc:
            assert get_recommendations([make_event()], "recommendations.yml") == ["r"]
        assert rc.call_args[0][2] == "secret"

    def test_unexpected_failure_returns_empty(self, monkeypatch):
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
        with patch("src.recommender.recommend_classes", side_effect=RuntimeError):
            assert get_recommendations([make_event()], "recommendations.yml") == []
