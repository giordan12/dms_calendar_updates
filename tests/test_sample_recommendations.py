from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from scripts import sample_recommendations as script


def make_events(n_classes, n_other=3):
    classes = [
        {
            "title": f"Class {i}",
            "link": f"http://example.com/{i}",
            "when": "Mon 10am",
            "description": "d",
            "categories": ["Class"],
        }
        for i in range(n_classes)
    ]
    other = [
        {"title": f"Event {i}", "link": "", "when": "", "description": "", "categories": ["Event"]}
        for i in range(n_other)
    ]
    return other + classes


def fake_client(scores_by_title, default=0.1):
    def system_one(*, state, questions, model):
        return SimpleNamespace(
            nouls={
                key: SimpleNamespace(
                    noul=scores_by_title.get(state["classes"][key]["title"], default)
                )
                for key in questions
            }
        )

    client = MagicMock()
    client.system_one.side_effect = system_one
    return client


class TestSampleClasses:
    def test_samples_only_classes(self):
        sample = script.sample_classes(make_events(30), 20, seed=1)
        assert len(sample) == 20
        assert all("Class" in e["categories"] for e in sample)

    def test_fewer_classes_than_count_returns_all(self):
        assert len(script.sample_classes(make_events(5), 20)) == 5

    def test_seed_is_repeatable(self):
        events = make_events(50)
        assert script.sample_classes(events, 20, seed=7) == script.sample_classes(events, 20, seed=7)

    def test_no_classes(self):
        assert script.sample_classes(make_events(0), 20) == []


class TestFormatRecommendation:
    def test_includes_score_title_when_link(self):
        text = script.format_recommendation(
            {"title": "Pottery", "yes_probability": 0.876, "when": "Mon", "link": "http://x"}
        )
        assert "0.88" in text and "Pottery" in text and "Mon" in text and "http://x" in text


class TestMain:
    @pytest.fixture(autouse=True)
    def _key(self, monkeypatch):
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")

    def _run(self, events, scores_by_title, argv=("--seed", "1")):
        client = fake_client(scores_by_title)
        with patch("scripts.sample_recommendations.fetch_feed", return_value="<xml/>"), \
             patch("scripts.sample_recommendations.parse_feed", return_value=events), \
             patch("scripts.sample_recommendations.TypeSafeClient") as client_cls:
            client_cls.return_value.__enter__.return_value = client
            code = script.main(list(argv))
        return code, client, client_cls

    def test_prints_only_recommended_sorted_by_score(self, capsys):
        scores = {"Class 0": 0.7, "Class 1": 0.2, "Class 2": 0.9}
        code, client, client_cls = self._run(make_events(3), scores)
        out = capsys.readouterr().out
        assert code == 0
        assert client.system_one.call_count == 1  # whole sample scored in one request
        assert len(client.system_one.call_args.kwargs["questions"]) == 3
        assert client_cls.call_args.kwargs["api_key"] == "k"
        assert "Recommended (noul > 0.6): 2 of 3" in out
        recommended_section = out.split("Recommended (noul")[1]
        assert recommended_section.index("0.90") < recommended_section.index("0.70")
        assert "0.20" not in recommended_section

    def test_respects_count(self):
        _, client, _ = self._run(make_events(30), {}, argv=("--count", "5"))
        assert len(client.system_one.call_args.kwargs["questions"]) == 5

    def test_no_classes_makes_no_calls(self, capsys):
        code, client, _ = self._run(make_events(0), {})
        assert code == 0
        client.system_one.assert_not_called()
        assert "Sampled 0 of 0" in capsys.readouterr().out

    def test_missing_api_key_exits_1(self, monkeypatch, capsys):
        monkeypatch.delenv("TYPESAFE_API_KEY")
        with patch("scripts.sample_recommendations.fetch_feed") as fetch:
            assert script.main([]) == 1
        fetch.assert_not_called()
        assert "TYPESAFE_API_KEY" in capsys.readouterr().err

    def test_bad_config_exits_1(self, tmp_path, capsys):
        with patch("scripts.sample_recommendations.fetch_feed") as fetch:
            assert script.main(["--config", str(tmp_path / "nope.yml")]) == 1
        fetch.assert_not_called()
