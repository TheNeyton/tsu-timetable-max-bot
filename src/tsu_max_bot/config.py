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
    alice_enabled: bool = False
    alice_host: str = "127.0.0.1"
    alice_port: int = 8080
    alice_webhook_path: str = field(default="/alice/webhook", repr=False)
    alice_skill_id: str | None = None
    yandex_api_key: str | None = field(default=None, repr=False)
    yandex_folder_id: str | None = None
    yandex_model: str = "yandexgpt-5-pro"
    speechkit_api_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(".env")
        token = os.getenv("MAX_BOT_TOKEN", "").strip()
        alice_enabled = _flag_from_env("ALICE_ENABLED")
        if not token and not alice_enabled:
            raise ConfigurationError("Укажите MAX_BOT_TOKEN в .env или переменных окружения.")
        alice_host = os.getenv("ALICE_HOST", cls.alice_host).strip()
        alice_path = os.getenv("ALICE_WEBHOOK_PATH", cls.alice_webhook_path).strip()
        alice_port = cls.alice_port
        if alice_enabled:
            if not alice_host:
                raise ConfigurationError("Укажите адрес прослушивания ALICE_HOST.")
            if (
                not alice_path.startswith("/")
                or alice_path.startswith("//")
                or any(not (c.isascii() and (c.isalnum() or c in "/_-")) for c in alice_path)
            ):
                raise ConfigurationError("Укажите путь вебхука в ALICE_WEBHOOK_PATH.")
            alice_port = _port_from_env()

        yandex_api_key = os.getenv("YANDEX_API_KEY", "").strip() or None
        yandex_folder_id = os.getenv("YANDEX_FOLDER_ID", "").strip() or None
        if bool(yandex_api_key) != bool(yandex_folder_id):
            raise ConfigurationError(
                "Для Yandex AI Studio задайте YANDEX_API_KEY и YANDEX_FOLDER_ID."
            )

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
            alice_enabled=alice_enabled,
            alice_host=alice_host,
            alice_port=alice_port,
            alice_webhook_path=alice_path,
            alice_skill_id=os.getenv("ALICE_SKILL_ID", "").strip() or None,
            yandex_api_key=yandex_api_key,
            yandex_folder_id=yandex_folder_id,
            yandex_model=os.getenv("YANDEX_MODEL", cls.yandex_model).strip() or cls.yandex_model,
            speechkit_api_key=os.getenv("SPEECHKIT_API_KEY", "").strip() or None,
        )


def _flag_from_env(name: str) -> bool:
    value = os.getenv(name, "false").strip().casefold()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no", ""}:
        return False
    raise ConfigurationError(f"Укажите true или false в {name}.")


def _port_from_env() -> int:
    try:
        port = int(os.getenv("ALICE_PORT", str(Settings.alice_port)))
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise ConfigurationError("Укажите порт от 1 до 65535 в ALICE_PORT.")
    return port


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
