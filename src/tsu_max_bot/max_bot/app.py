import asyncio
import logging
from contextlib import AsyncExitStack

import httpx
from aiohttp import web
from maxapi import Bot, Dispatcher

from tsu_max_bot.alice import create_alice_app
from tsu_max_bot.config import Settings
from tsu_max_bot.max_bot.registration import Registration
from tsu_max_bot.max_bot.voice import SpeechKit
from tsu_max_bot.schedule.alice_handler import AliceSchedule
from tsu_max_bot.schedule.service import ScheduleService
from tsu_max_bot.storage import Database
from tsu_max_bot.timetable import TimetableClient
from tsu_max_bot.yandex_assistant import YandexAssistant

logger = logging.getLogger(__name__)


async def run_bot(settings: Settings) -> None:
    async with AsyncExitStack() as resources:
        http = await resources.enter_async_context(httpx.AsyncClient())
        timetable = TimetableClient(
            http, base_url=settings.tsu_api_base_url, timeout=settings.tsu_api_timeout
        )
        assistant = None
        if settings.yandex_api_key and settings.yandex_folder_id:
            assistant = YandexAssistant(
                http,
                api_key=settings.yandex_api_key,
                folder_id=settings.yandex_folder_id,
                model=settings.yandex_model,
            )
        schedules = ScheduleService(timetable, rewrite=assistant.rewrite if assistant else None)

        max_polling = None
        if settings.max_bot_token:
            max_polling = await _configure_max(resources, settings, http, timetable, schedules)
        if settings.alice_enabled:
            await _start_alice(resources, settings, schedules)
        if max_polling is not None:
            dispatcher, bot = max_polling
            logger.info("Бот MAX запущен. Для остановки нажмите Ctrl+C.")
            await dispatcher.start_polling(bot)
        elif settings.alice_enabled:
            await asyncio.Event().wait()


async def _configure_max(
    resources: AsyncExitStack,
    settings: Settings,
    http: httpx.AsyncClient,
    timetable: TimetableClient,
    schedules: ScheduleService,
) -> tuple[Dispatcher, Bot]:
    database = Database(settings.database_url)
    resources.push_async_callback(database.close)
    bot = Bot(token=settings.max_bot_token, auto_requests=False, auto_check_subscriptions=False)
    resources.push_async_callback(bot.close_session)
    dispatcher = Dispatcher()
    resources.push_async_callback(dispatcher.shutdown)

    speechkit = (
        SpeechKit(http, api_key=settings.speechkit_api_key) if settings.speechkit_api_key else None
    )
    registration = Registration(
        timetable,
        database,
        schedules=schedules,
        transcribe=speechkit.transcribe if speechkit else None,
    )
    dispatcher.bot_started()(registration.bot_started)
    dispatcher.message_created()(registration.message_created)
    dispatcher.message_callback()(registration.message_callback)

    subscriptions = await bot.get_subscriptions()
    if subscriptions.subscriptions:
        raise RuntimeError(
            "У бота настроен webhook. Удалите подписку перед запуском через polling."
        )
    await database.migrate()
    return dispatcher, bot


async def _start_alice(
    resources: AsyncExitStack, settings: Settings, schedules: ScheduleService
) -> None:
    app = create_alice_app(
        AliceSchedule(schedules), path=settings.alice_webhook_path, skill_id=settings.alice_skill_id
    )
    runner = web.AppRunner(app, access_log=None)
    resources.push_async_callback(runner.cleanup)
    await runner.setup()
    await web.TCPSite(runner, settings.alice_host, settings.alice_port).start()
    logger.info("Вебхук Алисы запущен на %s:%s.", settings.alice_host, settings.alice_port)
