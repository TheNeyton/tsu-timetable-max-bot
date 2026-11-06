import asyncio
import logging

from tsu_max_bot.config import ConfigurationError, Settings
from tsu_max_bot.max_bot.app import run_bot


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        raise SystemExit(str(error)) from None

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run_bot(settings))
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Бот остановлен.")


if __name__ == "__main__":
    main()
