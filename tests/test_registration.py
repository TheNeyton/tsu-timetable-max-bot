import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from maxapi.types import BotStarted, MessageCallback, MessageCreated
from sqlalchemy.exc import SQLAlchemyError

from tsu_max_bot.max_bot.registration import Registration
from tsu_max_bot.storage import Database, RegisteredUser
from tsu_max_bot.timetable import TimetableClient

USER_ID = 4_200_000_001
USER = {"user_id": USER_ID, "first_name": "Студент", "is_bot": False}
RECIPIENT = {"chat_id": 12, "chat_type": "dialog"}
FACULTIES = [{"id": "science", "name": "Физический факультет"}]
GROUPS = [
    {"id": f"group-{number}", "name": f"Группа {number:02}", "isSubgroup": False}
    for number in range(1, 43)
]


def max_bot():
    return SimpleNamespace(
        send_message=AsyncMock(),
        send_callback=AsyncMock(return_value=SimpleNamespace(success=True)),
        resolve_format=lambda value: value,
    )


def start_button(bot):
    return BotStarted(timestamp=0, chat_id=12, user=USER, bot=bot)


def message(bot, text, *, chat_type="dialog"):
    return MessageCreated(
        timestamp=0,
        message={
            "timestamp": 0,
            "sender": USER,
            "recipient": {**RECIPIENT, "chat_type": chat_type},
            "body": {"mid": "message", "seq": 1, "text": text},
            "bot": bot,
        },
    )


def callback(bot, payload, *, user_id=USER_ID):
    return MessageCallback(
        timestamp=0,
        callback={
            "timestamp": 0,
            "callback_id": "callback",
            "payload": payload,
            "user": {**USER, "user_id": user_id},
        },
        message={
            "timestamp": 0,
            "recipient": RECIPIENT,
            "body": {"mid": "message", "seq": 1, "text": "Регистрация"},
        },
        bot=bot,
    )


def latest_keyboard(bot):
    if bot.send_callback.await_args and (edited := bot.send_callback.await_args.kwargs["message"]):
        text, attachments = edited.text, edited.attachments
    else:
        sent = bot.send_message.await_args.kwargs
        text, attachments = sent["text"], sent["attachments"]
    rows = attachments[0].payload.buttons
    assert len(rows) <= 30
    assert all(len(row) <= 7 for row in rows)
    return text, {button.text: button.payload for row in rows for button in row}


def test_max_start_registers_from_catalog_and_restores_profile(tmp_path):
    async def run():
        path = (tmp_path / "registration.sqlite3").as_posix()
        database = Database(f"sqlite+aiosqlite:///{path}")
        await database.migrate()
        api_paths = []

        def catalog(request):
            api_paths.append(request.url.path)
            match request.url.path:
                case "/api/web/v1/faculties":
                    return httpx.Response(200, json=FACULTIES)
                case "/api/web/v1/faculties/science/groups":
                    return httpx.Response(200, json=GROUPS)
            return httpx.Response(404)

        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(catalog)) as http:
                registration = Registration(TimetableClient(http), database)
                bot = max_bot()
                await registration.bot_started(start_button(bot))
                faculty_text, faculty_buttons = latest_keyboard(bot)
                assert FACULTIES[0]["name"] in faculty_text
                faculty = next(iter(faculty_buttons.values()))

                await registration.message_callback(callback(bot, faculty, user_id=USER_ID + 1))
                assert api_paths == ["/api/web/v1/faculties"]
                await registration.message_callback(callback(bot, faculty))
                group_text, group_buttons = latest_keyboard(bot)
                assert "Группа 01" in group_text
                first_group = next(iter(group_buttons.values()))
                for _ in range(len(GROUPS)):
                    if "Группа 42" in group_text:
                        break
                    await registration.message_callback(callback(bot, group_buttons["Далее"]))
                    group_text, group_buttons = latest_keyboard(bot)
                assert "Группа 42" in group_text

                await registration.message_callback(callback(bot, first_group))
                assert await database.get_user(USER_ID) is None
                last_group = group_buttons["42"]
                await asyncio.gather(
                    registration.message_callback(callback(bot, last_group)),
                    registration.message_callback(callback(bot, last_group)),
                )
                confirmations = [
                    call.kwargs["message"].text
                    for call in bot.send_callback.await_args_list
                    if call.kwargs["message"] is not None and not call.kwargs["message"].attachments
                ]
                assert len(confirmations) == 1
                assert await database.get_user(USER_ID) == RegisteredUser(
                    max_user_id=USER_ID,
                    faculty_id="science",
                    faculty_name="Физический факультет",
                    group_id="group-42",
                    group_name="Группа 42",
                )

                restarted = Registration(TimetableClient(http), database)
                await restarted.message_created(message(bot, "/start"))
                reply = bot.send_message.await_args.kwargs["text"]
                assert "Физический факультет" in reply
                assert "Группа 42" in reply
                assert api_paths == [
                    "/api/web/v1/faculties",
                    "/api/web/v1/faculties/science/groups",
                ]
        finally:
            await database.close()

    asyncio.run(run())


def test_group_callback_can_retry_after_catalog_and_database_failure():
    async def run():
        get_groups = AsyncMock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(200, json=GROUPS[:1]),
            ]
        )

        async def catalog(request):
            if request.url.path.endswith("/groups"):
                return await get_groups()
            return httpx.Response(200, json=FACULTIES)

        database = SimpleNamespace(
            get_user=AsyncMock(return_value=None),
            save_user=AsyncMock(side_effect=[SQLAlchemyError("offline"), None]),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(catalog)) as http:
            registration = Registration(TimetableClient(http), database)
            bot = max_bot()
            await registration.message_created(message(bot, "/start"))
            _, faculty_buttons = latest_keyboard(bot)
            faculty = next(iter(faculty_buttons.values()))
            await registration.message_callback(callback(bot, faculty))
            assert bot.send_callback.await_args.kwargs["notification"]
            await registration.message_callback(callback(bot, faculty))
            _, group_buttons = latest_keyboard(bot)
            group = next(iter(group_buttons.values()))

            await registration.message_callback(callback(bot, group))
            assert bot.send_callback.await_args.kwargs["notification"]
            await registration.message_callback(callback(bot, group))
            assert "Группа 01" in bot.send_callback.await_args.kwargs["message"].text
            assert database.save_user.await_count == 2

    asyncio.run(run())


def test_other_messages_keep_echo_behavior():
    async def run():
        database = SimpleNamespace(get_user=AsyncMock())
        async with httpx.AsyncClient() as http:
            registration = Registration(TimetableClient(http), database)
            bot = max_bot()
            for text, chat_type in [("<b>Привет</b>", "dialog"), ("/start", "chat")]:
                await registration.message_created(message(bot, text, chat_type=chat_type))
                assert bot.send_message.await_args.kwargs["text"] == text
        database.get_user.assert_not_awaited()

    asyncio.run(run())
