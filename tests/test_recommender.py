import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx2
import pytest
import yaml
from typesafe_sdk import Noul, RetryPolicy, TypeSafeClient, TypeSafeError, TypeSafeInternalServerError

from src.recommender import (
    QUESTION_ID,
    RecommenderConfigError,
    build_class_state,
    build_noul_question,
    get_recommendations,
    load_recommender_config,
    recommend_classes,
    score_class,
    select_classes,
)

CONFIG = {
    "enabled": True,
    "model": "jev-test",
    "threshold": 0.6,
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


def jev_response(noul):
    """Stand-in for typesafe_sdk.SystemOneResponse."""
    return SimpleNamespace(nouls={QUESTION_ID: SimpleNamespace(noul=noul)})


def fake_client(*results):
    client = MagicMock()
    client.system_one.side_effect = list(results)
    return client


class TestLoadConfig:
    def test_tracked_config_is_valid(self):
        config = load_recommender_config("recommendations.yml")
        assert config["instructions"].strip()
        assert 0 < config["threshold"] < 1
        assert config["model"].startswith("jev-")
        assert config["model"] != "jev-latest"  # pinned to a specific version

    def test_defaults_applied(self, tmp_path):
        path = tmp_path / "r.yml"
        path.write_text(yaml.dump({"model": "m", "instructions": "i", "threshold": 0.5}))
        config = load_recommender_config(str(path))
        assert config["enabled"] is True
        assert config["max_description_chars"] == 1500

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
        assert [e["title"] for e in select_classes(events)] == ["A"]

    def test_handles_missing_categories(self):
        assert select_classes([{"title": "x"}]) == []


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
        question = build_noul_question(CONFIG)
        assert isinstance(question, Noul)
        assert question.instructions == "Recommend this?"
        assert question.criteria == {"true": "good", "false": "bad"}

    def test_without_criteria(self):
        config = {k: v for k, v in CONFIG.items() if k != "criteria"}
        assert build_noul_question(config).criteria is None


class TestScoreClass:
    def test_calls_system_one_and_returns_noul(self):
        client = fake_client(jev_response(0.8))
        assert score_class(make_event(), CONFIG, client) == 0.8
        _, kwargs = client.system_one.call_args
        assert kwargs["model"] == "jev-test"
        assert kwargs["state"]["title"] == "Laser Basics"
        assert list(kwargs["questions"]) == [QUESTION_ID]
        assert kwargs["questions"][QUESTION_ID].instructions == "Recommend this?"

    def test_sdk_error_propagates(self):
        client = MagicMock()
        client.system_one.side_effect = TypeSafeError("boom")
        with pytest.raises(TypeSafeError):
            score_class(make_event(), CONFIG, client)


class TestSdkContract:
    """Runs the real SDK against a fake HTTP transport to pin the wire format."""

    def _client(self, handler):
        return TypeSafeClient(
            api_key="key123",
            transport=httpx2.MockTransport(handler),
            retry=RetryPolicy(max_retries=0),
        )

    def test_request_shape_and_noul_parsing(self):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers["authorization"]
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx2.Response(
                200,
                json={
                    "model": "jev-1.13.0",
                    "answers": {QUESTION_ID: {"type": "noul", "noul": 0.87}},
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )

        with self._client(handler) as client:
            assert score_class(make_event(), CONFIG, client) == 0.87

        assert seen["auth"] == "Bearer key123"
        assert seen["url"].endswith("/v1/systemone")
        assert seen["body"]["model"] == "jev-test"
        assert seen["body"]["state"]["title"] == "Laser Basics"
        question = seen["body"]["questions"][QUESTION_ID]
        assert question["type"] == "noul"
        assert question["instructions"] == "Recommend this?"
        assert question["criteria"] == {"true": "good", "false": "bad"}

    def test_server_error_raises_typesafe_error(self):
        def handler(request):
            return httpx2.Response(500, json={"error": "down"})

        with self._client(handler) as client:
            with pytest.raises(TypeSafeInternalServerError):
                score_class(make_event(), CONFIG, client)


class TestRecommendClasses:
    def test_only_above_threshold_recommended(self):
        events = [make_event("A"), make_event("B"), make_event("C")]
        client = fake_client(jev_response(0.61), jev_response(0.6), jev_response(0.2))
        result = recommend_classes(events, CONFIG, client)
        assert [e["title"] for e in result] == ["A"]
        assert result[0]["yes_probability"] == 0.61

    def test_threshold_is_strict(self):
        client = fake_client(jev_response(0.6))
        assert recommend_classes([make_event()], CONFIG, client) == []

    def test_non_classes_not_sent_to_jev(self):
        events = [make_event("A"), make_event("Tour", categories=["Event"])]
        client = fake_client(jev_response(0.9))
        recommend_classes(events, CONFIG, client)
        assert client.system_one.call_count == 1

    def test_one_call_per_class(self):
        events = [make_event(str(i)) for i in range(4)]
        client = fake_client(*[jev_response(0.1)] * 4)
        recommend_classes(events, CONFIG, client)
        assert client.system_one.call_count == 4

    def test_failed_class_skipped_others_continue(self):
        events = [make_event("A"), make_event("B")]
        client = fake_client(TypeSafeError("x"), jev_response(0.9))
        result = recommend_classes(events, CONFIG, client)
        assert [e["title"] for e in result] == ["B"]

    def test_missing_answer_skipped(self):
        client = fake_client(SimpleNamespace(nouls={}))
        assert recommend_classes([make_event()], CONFIG, client) == []


class TestGetRecommendations:
    def test_no_api_key_skips(self, monkeypatch):
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        with patch("src.recommender.TypeSafeClient") as client_cls:
            assert get_recommendations([make_event()], "recommendations.yml") == []
        client_cls.assert_not_called()

    def test_disabled_skips(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
        path = tmp_path / "r.yml"
        path.write_text(
            yaml.dump(
                {"model": "m", "instructions": "i", "threshold": 0.5, "enabled": False}
            )
        )
        with patch("src.recommender.TypeSafeClient") as client_cls:
            assert get_recommendations([make_event()], str(path)) == []
        client_cls.assert_not_called()

    def test_bad_config_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
        assert get_recommendations([make_event()], str(tmp_path / "nope.yml")) == []

    def test_builds_client_with_env_key_and_returns_results(self, monkeypatch):
        monkeypatch.setenv("TYPESAFE_API_KEY", "secret")
        with patch("src.recommender.TypeSafeClient") as client_cls:
            client_cls.return_value.__enter__.return_value = fake_client(
                jev_response(0.9)
            )
            result = get_recommendations([make_event()], "recommendations.yml")
        assert [e["title"] for e in result] == ["Laser Basics"]
        assert client_cls.call_args.kwargs["api_key"] == "secret"

    def test_unexpected_failure_returns_empty(self, monkeypatch):
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
        with patch("src.recommender.TypeSafeClient", side_effect=RuntimeError):
            assert get_recommendations([make_event()], "recommendations.yml") == []
