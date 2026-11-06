from unittest.mock import patch

import pytest

from tsu_max_bot.config import ConfigurationError, Settings


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in ("MAX_BOT_TOKEN", "TSU_API_BASE_URL", "TSU_API_TIMEOUT", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)


def test_missing_token_has_actionable_error():
    with pytest.raises(ConfigurationError, match="MAX_BOT_TOKEN"):
        Settings.from_env()


def test_dotenv_is_loaded_and_environment_takes_precedence(tmp_path):
    (tmp_path / ".env").write_text("MAX_BOT_TOKEN=from-file\nTSU_API_TIMEOUT=7\n", encoding="utf-8")
    with patch.dict("os.environ", {"MAX_BOT_TOKEN": "from-environment"}, clear=True):
        settings = Settings.from_env()
        assert settings.max_bot_token == "from-environment"
        assert settings.tsu_api_timeout == 7


def test_settings_read_environment_without_exposing_token(monkeypatch):
    monkeypatch.setenv("MAX_BOT_TOKEN", " secret ")
    monkeypatch.setenv("TSU_API_BASE_URL", "https://example.org/api")
    monkeypatch.setenv("TSU_API_TIMEOUT", "3.5")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    settings = Settings.from_env()

    assert settings.max_bot_token == "secret"
    assert settings.tsu_api_base_url == "https://example.org/api/"
    assert settings.tsu_api_timeout == 3.5
    assert settings.log_level == "DEBUG"
    assert "secret" not in repr(settings)


@pytest.mark.parametrize("timeout", ["abc", "0", "-1", "nan", "inf"])
def test_invalid_timeout_is_rejected(monkeypatch, timeout):
    monkeypatch.setenv("MAX_BOT_TOKEN", "secret")
    monkeypatch.setenv("TSU_API_TIMEOUT", timeout)
    with pytest.raises(ConfigurationError, match="TSU_API_TIMEOUT"):
        Settings.from_env()


@pytest.mark.parametrize(
    ("name", "value"),
    [("TSU_API_BASE_URL", "example.org"), ("LOG_LEVEL", "VERBOSE")],
)
def test_invalid_config_is_rejected(monkeypatch, name, value):
    monkeypatch.setenv("MAX_BOT_TOKEN", "secret")
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError, match=name):
        Settings.from_env()
