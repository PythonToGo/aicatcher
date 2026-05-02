"""Unit tests for config.py Settings."""

import pytest
from unittest.mock import patch

from newsbot.config import Settings, get_settings


REQUIRED_ENV = {"anthropic_api_key": "test-key"}


class TestSettings:
    def test_minimal_valid_settings(self) -> None:
        s = Settings(**REQUIRED_ENV)
        assert s.anthropic_api_key == "test-key"
        assert s.dry_run is False
        assert s.default_language == "ko"
        assert s.items_per_report == 6
        assert s.anthropic_main_model == "claude-sonnet-4-6"
        assert s.anthropic_quality_model == "claude-haiku-4-5-20251001"

    def test_dry_run_flag(self) -> None:
        s = Settings(**REQUIRED_ENV, dry_run=True)
        assert s.dry_run is True

    def test_invalid_language_raises(self) -> None:
        with pytest.raises(Exception):
            Settings(**REQUIRED_ENV, default_language="ja")

    def test_log_level_uppercased(self) -> None:
        s = Settings(**REQUIRED_ENV, log_level="debug")
        assert s.log_level == "DEBUG"

    def test_invalid_log_level_raises(self) -> None:
        with pytest.raises(Exception):
            Settings(**REQUIRED_ENV, log_level="VERBOSE")

    def test_twitter_configured_false_when_empty(self) -> None:
        s = Settings(**REQUIRED_ENV)
        assert s.twitter_configured is False

    def test_twitter_configured_true_when_all_set(self) -> None:
        s = Settings(
            **REQUIRED_ENV,
            twitter_bearer_token="bt",
            twitter_api_key="ak",
            twitter_api_secret="as",
            twitter_access_token="at",
            twitter_access_secret="as2",
        )
        assert s.twitter_configured is True

    def test_whatsapp_configured_false_when_partial(self) -> None:
        s = Settings(**REQUIRED_ENV, whatsapp_token="tok")
        assert s.whatsapp_configured is False

    def test_items_per_report_bounds(self) -> None:
        with pytest.raises(Exception):
            Settings(**REQUIRED_ENV, items_per_report=0)
        with pytest.raises(Exception):
            Settings(**REQUIRED_ENV, items_per_report=21)


class TestGetSettings:
    def test_returns_settings_instance(self) -> None:
        get_settings.cache_clear()
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"}):
            s = get_settings()
            assert isinstance(s, Settings)
            assert s.anthropic_api_key == "env-key"

    def test_singleton_caching(self) -> None:
        get_settings.cache_clear()
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"}):
            s1 = get_settings()
            s2 = get_settings()
            assert s1 is s2
