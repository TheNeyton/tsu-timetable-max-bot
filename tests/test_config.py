from unittest.mock import patch

import pytest

from tsu_max_bot.config import ConfigurationError, Settings


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    names = ("MAX_BOT_TOKEN", "TSU_API_BASE_URL", "TSU_API_TIMEOUT", "LOG_LEVEL", "DATABASE_URL")
    for name in names:
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


def test_database_defaults_to_local_sqlite(monkeypatch):
    monkeypatch.setenv("MAX_BOT_TOKEN", "token")
    assert Settings.from_env().database_url == "sqlite+aiosqlite:///tsu_max_bot.sqlite3"


def test_mysql_url_selects_async_driver_without_exposing_password(monkeypatch):
    monkeypatch.setenv("MAX_BOT_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", "mysql://bot:db-password@localhost:3306/timetable")

    settings = Settings.from_env()

    assert settings.database_url == "mysql+aiomysql://bot:db-password@localhost:3306/timetable"
    assert "db-password" not in repr(settings)


@pytest.mark.parametrize("url", ["postgresql://localhost/db", "mysql://bot@localhost", "sqlite://"])
def test_invalid_database_url_is_rejected(monkeypatch, url):
    monkeypatch.setenv("MAX_BOT_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", url)

    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        Settings.from_env()


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
