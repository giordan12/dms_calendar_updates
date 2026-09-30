import json
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


class TestStoredClasses:
    def test_round_trip_preserves_unicode(self, tmp_path):
        path = tmp_path / "c.json"
        classes = [{"title": "Café — Basics", "categories": ["Class"]}]
        script.save_stored_classes(classes, path)
        assert script.load_stored_classes(path) == classes

    def test_tracked_stored_classes_are_valid(self):
        classes = script.load_stored_classes(script.STORED_CLASSES_PATH)
        assert len(classes) > 0
        assert all("Class" in c["categories"] for c in classes)
        assert all(c["title"] for c in classes)


class TestMain:
    @pytest.fixture(autouse=True)
    def _key(self, monkeypatch):
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")

    @pytest.fixture
    def classes_file(self, tmp_path):
        return tmp_path / "stored.json"

    def _run(self, classes_file, scores_by_title=None, argv=(), feed_events=None):
        """Run main() with the SDK client faked and the site fetch patched."""
        client = fake_client(scores_by_title or {})
        with patch("scripts.sample_recommendations.fetch_feed", return_value="<xml/>") as fetch, \
             patch("scripts.sample_recommendations.parse_feed", return_value=feed_events or []), \
             patch("scripts.sample_recommendations.TypeSafeClient") as client_cls:
            client_cls.return_value.__enter__.return_value = client
            code = script.main(["--classes-file", str(classes_file), "--seed", "1", *argv])
        return code, client, client_cls, fetch

    def test_default_uses_stored_classes_and_never_queries_site(self, classes_file, capsys):
        script.save_stored_classes(make_events(3, n_other=0), classes_file)
        scores = {"Class 0": 0.7, "Class 1": 0.2, "Class 2": 0.9}
        code, client, client_cls, fetch = self._run(classes_file, scores)
        out = capsys.readouterr().out
        assert code == 0
        fetch.assert_not_called()
        assert "Loaded 3 stored classes" in out
        assert client.system_one.call_count == 1  # whole sample scored in one request
        assert len(client.system_one.call_args.kwargs["questions"]) == 3
        assert client_cls.call_args.kwargs["api_key"] == "k"

    def test_prints_only_recommended_sorted_by_score(self, classes_file, capsys):
        script.save_stored_classes(make_events(3, n_other=0), classes_file)
        scores = {"Class 0": 0.7, "Class 1": 0.2, "Class 2": 0.9}
        self._run(classes_file, scores)
        out = capsys.readouterr().out
        assert "Recommended (noul > 0.6): 2 of 3" in out
        recommended_section = out.split("Recommended (noul")[1]
        assert recommended_section.index("0.90") < recommended_section.index("0.70")
        assert "0.20" not in recommended_section

    def test_respects_count(self, classes_file):
        script.save_stored_classes(make_events(30, n_other=0), classes_file)
        _, client, _, _ = self._run(classes_file, argv=("--count", "5"))
        assert len(client.system_one.call_args.kwargs["questions"]) == 5

    def test_missing_stored_file_exits_1_and_suggests_live(self, classes_file, capsys):
        code, client, _, fetch = self._run(classes_file)
        assert code == 1
        assert "--live" in capsys.readouterr().err
        fetch.assert_not_called()
        client.system_one.assert_not_called()

    def test_corrupt_stored_file_exits_1(self, classes_file, capsys):
        classes_file.write_text("{not json")
        code, _, _, _ = self._run(classes_file)
        assert code == 1
        assert "--live" in capsys.readouterr().err

    def test_no_stored_classes_makes_no_calls(self, classes_file, capsys):
        script.save_stored_classes([], classes_file)
        code, client, _, _ = self._run(classes_file)
        assert code == 0
        client.system_one.assert_not_called()
        assert "Sampled 0 of 0" in capsys.readouterr().out

    @pytest.mark.parametrize("flag", ["--live", "--livemode"])
    def test_live_pulls_from_site_and_refreshes_stored_file(self, classes_file, capsys, flag):
        script.save_stored_classes(make_events(1, n_other=0), classes_file)  # stale
        feed = make_events(4, n_other=2)
        code, client, _, fetch = self._run(classes_file, argv=(flag,), feed_events=feed)
        out = capsys.readouterr().out
        assert code == 0
        fetch.assert_called_once()
        assert "Pulled 4 classes from the site" in out
        stored = json.loads(classes_file.read_text())
        assert [c["title"] for c in stored] == [f"Class {i}" for i in range(4)]  # classes only
        assert len(client.system_one.call_args.kwargs["questions"]) == 4

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
