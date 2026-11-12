import asyncio
import sqlite3
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from tsu_max_bot.config import Settings
from tsu_max_bot.max_bot.app import run_bot
from tsu_max_bot.max_bot.handlers import echo_message


@pytest.mark.parametrize("text", ["Здравствуйте!", "/start", "<b>Тест</b> **расписание**"])
def test_echo_preserves_text(text):
    answer = AsyncMock()
    event = SimpleNamespace(
        message=SimpleNamespace(
            sender=SimpleNamespace(is_bot=False), body=SimpleNamespace(text=text), answer=answer
        )
    )

    asyncio.run(echo_message(event))

    answer.assert_awaited_once_with(text)


@pytest.mark.parametrize(
    ("sender", "body"),
    [
        (None, SimpleNamespace(text="Привет")),
        (SimpleNamespace(is_bot=True), SimpleNamespace(text="Привет")),
        (SimpleNamespace(is_bot=False), None),
        (SimpleNamespace(is_bot=False), SimpleNamespace(text=None)),
        (SimpleNamespace(is_bot=False), SimpleNamespace(text="")),
    ],
)
def test_non_text_and_bot_messages_are_ignored(sender, body):
    answer = AsyncMock()
    event = SimpleNamespace(message=SimpleNamespace(sender=sender, body=body, answer=answer))

    asyncio.run(echo_message(event))

    answer.assert_not_awaited()


@pytest.mark.parametrize(
    "failure", ["webhook", "polling", "subscriptions", "migration", "shutdown", None]
)
def test_bot_closes_session_even_after_failure(monkeypatch, tmp_path, failure):
    database_directory = tmp_path / "missing" if failure == "migration" else tmp_path
    database_path = database_directory / "users.sqlite3"
    settings = Settings(
        max_bot_token="secret",
        database_url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    handlers = {}

    async def start_polling(bot):
        assert set(handlers) == {"message_created", "bot_started", "message_callback"}
        with closing(sqlite3.connect(database_path)) as connection:
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'registered_users'"
            ).fetchone()
        assert table == ("registered_users",)

    bot = SimpleNamespace(
        get_subscriptions=AsyncMock(
            return_value=SimpleNamespace(subscriptions=["webhook"] if failure == "webhook" else [])
        ),
        close_session=AsyncMock(),
    )
    dispatcher = SimpleNamespace(
        message_created=lambda: lambda handler: handlers.setdefault("message_created", handler),
        bot_started=lambda: lambda handler: handlers.setdefault("bot_started", handler),
        message_callback=lambda: lambda handler: handlers.setdefault("message_callback", handler),
        start_polling=AsyncMock(side_effect=start_polling),
        shutdown=AsyncMock(),
    )
    if failure == "polling":
        dispatcher.start_polling.side_effect = RuntimeError("polling failed")
    elif failure == "subscriptions":
        bot.get_subscriptions.side_effect = RuntimeError("subscriptions failed")
    elif failure == "shutdown":
        dispatcher.shutdown.side_effect = RuntimeError("shutdown failed")

    monkeypatch.setattr("tsu_max_bot.max_bot.app.Bot", lambda **kwargs: bot)
    monkeypatch.setattr("tsu_max_bot.max_bot.app.Dispatcher", lambda: dispatcher)

    if failure == "migration":
        with pytest.raises(OperationalError, match="unable to open database file"):
            asyncio.run(run_bot(settings))
    elif failure:
        with pytest.raises(RuntimeError):
            asyncio.run(run_bot(settings))
    else:
        asyncio.run(run_bot(settings))

    dispatcher.shutdown.assert_awaited_once()
    bot.close_session.assert_awaited_once()
    if failure in {"webhook", "subscriptions", "migration"}:
        dispatcher.start_polling.assert_not_awaited()
