import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx2
import pytest
import yaml
from typesafe_sdk import Noul, RetryPolicy, TypeSafeClient, TypeSafeError, TypeSafeInternalServerError

from src.recommender import (
    RecommenderConfigError,
    build_class_state,
    build_noul_question,
    get_recommendations,
    load_recommender_config,
    recommend_classes,
    score_batch,
    select_classes,
)

CONFIG = {
    "enabled": True,
    "model": "jev-test",
    "threshold": 0.6,
    "max_description_chars": 20,
    "batch_size": 20,
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


def fake_client(scores, fail_titles=()):
    """Client whose system_one answers each question with scores[class title].

    Titles missing from `scores` get no answer; a batch containing a title in
    `fail_titles` raises.
    """

    def system_one(*, state, questions, model):
        titles = {key: state["classes"][key]["title"] for key in questions}
        if any(title in fail_titles for title in titles.values()):
            raise TypeSafeError("boom")
        return SimpleNamespace(
            nouls={
                key: SimpleNamespace(noul=scores[title])
                for key, title in titles.items()
                if title in scores
            }
        )

    client = MagicMock()
    client.system_one.side_effect = system_one
    return client


class TestLoadConfig:
    def test_tracked_config_is_valid(self):
        config = load_recommender_config("recommendations.yml")
        assert config["instructions"].strip()
        assert 0 < config["threshold"] < 1
        assert config["model"].startswith("jev-")
        assert config["model"] != "jev-latest"  # pinned to a specific version
        assert config["batch_size"] >= 1

    def test_defaults_applied(self, tmp_path):
        path = tmp_path / "r.yml"
        path.write_text(yaml.dump({"model": "m", "instructions": "i", "threshold": 0.5}))
        config = load_recommender_config(str(path))
        assert config["enabled"] is True
        assert config["max_description_chars"] == 1500
        assert config["batch_size"] == 20

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

    def test_invalid_batch_size_raises(self, tmp_path):
        path = tmp_path / "r.yml"
        path.write_text(
            yaml.dump({"model": "m", "instructions": "i", "threshold": 0.5, "batch_size": 0})
        )
        with pytest.raises(RecommenderConfigError, match="batch_size"):
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
    def test_with_criteria_and_class_reference(self):
        question = build_noul_question(CONFIG, "class_3")
        assert isinstance(question, Noul)
        assert question.instructions.startswith("Recommend this?")
        assert 'class with id "class_3"' in question.instructions
        assert question.criteria == {"true": "good", "false": "bad"}

    def test_without_criteria(self):
        config = {k: v for k, v in CONFIG.items() if k != "criteria"}
        assert build_noul_question(config, "class_0").criteria is None


class TestScoreBatch:
    def test_one_request_with_a_question_per_class(self):
        events = [make_event("A"), make_event("B"), make_event("C")]
        client = fake_client({"A": 0.1, "B": 0.5, "C": 0.9})
        assert score_batch(events, CONFIG, client) == [0.1, 0.5, 0.9]
        client.system_one.assert_called_once()
        kwargs = client.system_one.call_args.kwargs
        assert kwargs["model"] == "jev-test"
        assert list(kwargs["state"]["classes"]) == ["class_0", "class_1", "class_2"]
        assert list(kwargs["questions"]) == ["class_0", "class_1", "class_2"]
        assert kwargs["state"]["classes"]["class_1"]["title"] == "B"

    def test_missing_answer_is_none(self):
        events = [make_event("A"), make_event("B")]
        client = fake_client({"B": 0.7})
        assert score_batch(events, CONFIG, client) == [None, 0.7]

    def test_sdk_error_propagates(self):
        client = fake_client({}, fail_titles={"A"})
        with pytest.raises(TypeSafeError):
            score_batch([make_event("A")], CONFIG, client)


class TestSdkContract:
    """Runs the real SDK against a fake HTTP transport to pin the wire format."""

    def _client(self, handler):
        return TypeSafeClient(
            api_key="key123",
            transport=httpx2.MockTransport(handler),
            retry=RetryPolicy(max_retries=0),
        )

    def test_request_shape_and_answer_parsing(self):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers["authorization"]
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx2.Response(
                200,
                json={
                    "model": "jev-1.13.0",
                    "answers": {
                        "class_0": {"type": "noul", "noul": 0.87},
                        "class_1": {"type": "noul", "noul": 0.12},
                    },
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )

        events = [make_event("A"), make_event("B")]
        with self._client(handler) as client:
            assert score_batch(events, CONFIG, client) == [0.87, 0.12]

        assert seen["auth"] == "Bearer key123"
        assert seen["url"].endswith("/v1/systemone")
        body = seen["body"]
        assert body["model"] == "jev-test"
        assert body["state"]["classes"]["class_0"]["title"] == "A"
        assert body["state"]["classes"]["class_1"]["title"] == "B"
        assert set(body["questions"]) == {"class_0", "class_1"}
        question = body["questions"]["class_1"]
        assert question["type"] == "noul"
        assert 'class with id "class_1"' in question["instructions"]
        assert question["criteria"] == {"true": "good", "false": "bad"}

    def test_server_error_raises_typesafe_error(self):
        def handler(request):
            return httpx2.Response(500, json={"error": "down"})

        with self._client(handler) as client:
            with pytest.raises(TypeSafeInternalServerError):
                score_batch([make_event()], CONFIG, client)


class TestRecommendClasses:
    def test_only_above_threshold_recommended(self):
        events = [make_event("A"), make_event("B"), make_event("C")]
        client = fake_client({"A": 0.61, "B": 0.6, "C": 0.2})
        result = recommend_classes(events, CONFIG, client)
        assert [e["title"] for e in result] == ["A"]
        assert result[0]["yes_probability"] == 0.61

    def test_threshold_is_strict(self):
        client = fake_client({"Laser Basics": 0.6})
        assert recommend_classes([make_event()], CONFIG, client) == []

    def test_non_classes_not_sent_to_jev(self):
        events = [make_event("A"), make_event("Tour", categories=["Event"])]
        client = fake_client({"A": 0.9, "Tour": 0.9})
        result = recommend_classes(events, CONFIG, client)
        assert [e["title"] for e in result] == ["A"]
        questions = client.system_one.call_args.kwargs["questions"]
        assert len(questions) == 1

    def test_all_classes_in_one_request_when_under_batch_size(self):
        events = [make_event(str(i)) for i in range(20)]
        client = fake_client({str(i): 0.1 for i in range(20)})
        recommend_classes(events, CONFIG, client)
        assert client.system_one.call_count == 1
        assert len(client.system_one.call_args.kwargs["questions"]) == 20

    def test_splits_into_batches_of_batch_size(self):
        events = [make_event(str(i)) for i in range(7)]
        config = {**CONFIG, "batch_size": 3}
        client = fake_client({str(i): 0.9 for i in range(7)})
        result = recommend_classes(events, config, client)
        sizes = [len(c.kwargs["questions"]) for c in client.system_one.call_args_list]
        assert sizes == [3, 3, 1]
        assert [e["title"] for e in result] == [str(i) for i in range(7)]

    def test_failed_batch_skipped_other_batches_continue(self):
        events = [make_event(str(i)) for i in range(4)]
        config = {**CONFIG, "batch_size": 2}
        client = fake_client({str(i): 0.9 for i in range(4)}, fail_titles={"0"})
        result = recommend_classes(events, config, client)
        assert [e["title"] for e in result] == ["2", "3"]

    def test_class_without_answer_skipped(self):
        events = [make_event("A"), make_event("B")]
        client = fake_client({"B": 0.9})
        result = recommend_classes(events, CONFIG, client)
        assert [e["title"] for e in result] == ["B"]

    def test_no_classes_makes_no_request(self):
        client = fake_client({})
        assert recommend_classes([make_event("T", categories=["Event"])], CONFIG, client) == []
        client.system_one.assert_not_called()


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
                {"Laser Basics": 0.9}
            )
            result = get_recommendations([make_event()], "recommendations.yml")
        assert [e["title"] for e in result] == ["Laser Basics"]
        assert client_cls.call_args.kwargs["api_key"] == "secret"

    def test_unexpected_failure_returns_empty(self, monkeypatch):
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
        with patch("src.recommender.TypeSafeClient", side_effect=RuntimeError):
            assert get_recommendations([make_event()], "recommendations.yml") == []
