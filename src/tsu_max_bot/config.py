import logging
import math
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    max_bot_token: str = field(repr=False)
    tsu_api_base_url: str = "https://intime.tsu.ru/api/web/v1/"
    tsu_api_timeout: float = 15.0
    log_level: str = "INFO"

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
        )
