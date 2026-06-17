"""Tests for configuration manager."""
import pytest
from core.config_manager import ConfigManager, AppConfig


class TestAppConfig:
    def test_default_config(self):
        config = AppConfig()
        assert config.language == "en"
        assert config.theme == "dark"
        assert config.view_mode == "list"
        assert config.upload_retry_times == 3
        assert config.max_concurrent_uploads == 1

    def test_telethon_defaults(self):
        config = AppConfig()
        assert config.telethon.logged_in is False
        assert config.telethon.user_id == 0

    def test_upload_limit_defaults(self):
        config = AppConfig()
        limits = config.upload_limit_settings
        assert limits.enabled is True
        assert limits.max_daily_size_gb == 10.0
        assert limits.max_daily_files == 100


class TestConfigManager:
    def test_load_defaults(self, tmp_path):
        """ConfigManager loads defaults when no config file exists."""
        import yaml
        config_path = tmp_path / "nonexistent.yaml"
        cm = ConfigManager(str(config_path))
        assert cm.config["language"] == "en"
        assert cm.config["view_mode"] == "list"

    def test_load_from_yaml(self, tmp_path):
        """ConfigManager loads from a YAML file."""
        import yaml
        config_path = tmp_path / "test_config.yaml"
        data = {"language": "zh", "theme": "light", "view_mode": "icon"}
        with open(config_path, "w") as f:
            yaml.dump(data, f)
        cm = ConfigManager(str(config_path))
        assert cm.config["language"] == "zh"
        assert cm.config["theme"] == "light"

    def test_has_valid_session_no_login(self):
        cm = ConfigManager("nonexistent.yaml")
        assert cm.has_valid_session() is False

    def test_set_language(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        cm = ConfigManager(str(config_path))
        cm.set_language("zh")
        assert cm.get_language() == "zh"

    def test_set_view_mode(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        cm = ConfigManager(str(config_path))
        cm.set_view_mode("icon")
        assert cm.get_view_mode() == "icon"
