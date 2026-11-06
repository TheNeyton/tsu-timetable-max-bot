import logging

from maxapi import Bot, Dispatcher

from tsu_max_bot.config import Settings
from tsu_max_bot.max_bot.handlers import echo_message

logger = logging.getLogger(__name__)


async def run_bot(settings: Settings) -> None:
    bot = Bot(token=settings.max_bot_token, auto_requests=False, auto_check_subscriptions=False)
    dispatcher = Dispatcher()
    dispatcher.message_created()(echo_message)

    try:
        subscriptions = await bot.get_subscriptions()
        if subscriptions.subscriptions:
            raise RuntimeError(
                "У бота настроен webhook. Удалите подписку перед запуском через polling."
            )
        logger.info("Эхо-бот MAX запущен. Для остановки нажмите Ctrl+C.")
        await dispatcher.start_polling(bot)
    finally:
        try:
            await dispatcher.shutdown()
        finally:
            await bot.close_session()
