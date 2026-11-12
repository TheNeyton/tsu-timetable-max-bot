import logging
from contextlib import AsyncExitStack

import httpx
from maxapi import Bot, Dispatcher

from tsu_max_bot.config import Settings
from tsu_max_bot.max_bot.registration import Registration
from tsu_max_bot.storage import Database
from tsu_max_bot.timetable import TimetableClient

logger = logging.getLogger(__name__)


async def run_bot(settings: Settings) -> None:
    async with AsyncExitStack() as resources:
        database = Database(settings.database_url)
        resources.push_async_callback(database.close)
        http = await resources.enter_async_context(httpx.AsyncClient())
        timetable = TimetableClient(
            http, base_url=settings.tsu_api_base_url, timeout=settings.tsu_api_timeout
        )
        bot = Bot(token=settings.max_bot_token, auto_requests=False, auto_check_subscriptions=False)
        resources.push_async_callback(bot.close_session)
        dispatcher = Dispatcher()
        resources.push_async_callback(dispatcher.shutdown)

        registration = Registration(timetable, database)
        dispatcher.bot_started()(registration.bot_started)
        dispatcher.message_created()(registration.message_created)
        dispatcher.message_callback()(registration.message_callback)

        subscriptions = await bot.get_subscriptions()
        if subscriptions.subscriptions:
            raise RuntimeError(
                "У бота настроен webhook. Удалите подписку перед запуском через polling."
            )
        await database.migrate()
        logger.info("Бот MAX запущен. Для остановки нажмите Ctrl+C.")
        await dispatcher.start_polling(bot)
