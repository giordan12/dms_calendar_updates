import pytest

from src.config import load_config


class TestLoadConfig:
    def test_loads_valid_config(self, tmp_path):
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            "schedule:\n  hour: 9\n  minute: 30\n  timezone: America/New_York\n"
            "notifications:\n  on_error: false\n",
            encoding="utf-8",
        )
        config = load_config(str(config_file))
        assert config["schedule"]["hour"] == 9
        assert config["schedule"]["minute"] == 30
        assert config["schedule"]["timezone"] == "America/New_York"
        assert config["notifications"]["on_error"] is False

    def test_missing_keys_use_defaults(self, tmp_path):
        config_file = tmp_path / "config.yml"
        config_file.write_text("schedule:\n  hour: 10\n", encoding="utf-8")
        config = load_config(str(config_file))
        assert config["schedule"]["hour"] == 10
        assert config["schedule"]["minute"] == 0
        assert config["schedule"]["timezone"] == "America/Chicago"
        assert config["notifications"]["on_error"] is True

    def test_missing_file_returns_defaults(self, tmp_path):
        config = load_config(str(tmp_path / "nonexistent.yml"))
        assert config["schedule"]["hour"] == 8
        assert config["schedule"]["minute"] == 0
        assert config["notifications"]["on_error"] is True

    def test_invalid_yaml_returns_defaults(self, tmp_path):
        config_file = tmp_path / "config.yml"
        config_file.write_text("{ this: is: not: valid: yaml: [[[", encoding="utf-8")
        config = load_config(str(config_file))
        assert config["schedule"]["hour"] == 8
        assert config["notifications"]["on_error"] is True
