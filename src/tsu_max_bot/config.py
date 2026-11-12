import logging
import math
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///tsu_max_bot.sqlite3"


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    max_bot_token: str = field(repr=False)
    tsu_api_base_url: str = "https://intime.tsu.ru/api/web/v1/"
    tsu_api_timeout: float = 15.0
    log_level: str = "INFO"
    database_url: str = field(default=DEFAULT_DATABASE_URL, repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(".env")
        token = os.getenv("MAX_BOT_TOKEN", "").strip()
        if not token:
            raise ConfigurationError("Укажите MAX_BOT_TOKEN в .env или переменных окружения.")

        base_url = os.getenv("TSU_API_BASE_URL", cls.tsu_api_base_url).strip()
        parsed_url = urlsplit(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ConfigurationError("TSU_API_BASE_URL должен быть HTTP или HTTPS URL.")

        try:
            timeout = float(os.getenv("TSU_API_TIMEOUT", str(cls.tsu_api_timeout)))
        except ValueError as error:
            raise ConfigurationError("TSU_API_TIMEOUT должен быть положительным числом.") from error
        if not math.isfinite(timeout) or timeout <= 0:
            raise ConfigurationError("TSU_API_TIMEOUT должен быть положительным числом.")

        log_level = os.getenv("LOG_LEVEL", cls.log_level).strip().upper()
        if log_level not in logging.getLevelNamesMapping():
            raise ConfigurationError("Укажите корректный LOG_LEVEL, например INFO или DEBUG.")

        return cls(
            max_bot_token=token,
            tsu_api_base_url=base_url.rstrip("/") + "/",
            tsu_api_timeout=timeout,
            log_level=log_level,
            database_url=_database_url_from_env(),
        )


def _database_url_from_env() -> str:
    try:
        url = make_url(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL).strip())
    except (ArgumentError, ValueError):
        raise ConfigurationError("Укажите корректный DATABASE_URL для SQLite или MySQL.") from None

    if url.drivername in {"sqlite", "sqlite+aiosqlite"}:
        if not url.database or any(
            part is not None for part in (url.username, url.password, url.host, url.port)
        ):
            raise ConfigurationError("Для SQLite укажите путь к файлу в DATABASE_URL.")
        url = url.set(drivername="sqlite+aiosqlite")
    elif url.drivername in {"mysql", "mysql+aiomysql"}:
        if not (url.host and url.username and url.database):
            raise ConfigurationError(
                "Укажите сервер, пользователя и базу в DATABASE_URL для MySQL."
            )
        url = url.set(drivername="mysql+aiomysql")
    else:
        raise ConfigurationError("DATABASE_URL должен использовать SQLite или MySQL.")

    return url.render_as_string(hide_password=False)
