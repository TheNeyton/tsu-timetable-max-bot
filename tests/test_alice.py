import asyncio
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tsu_max_bot.alice import AliceReply, AliceRequest, create_alice_app


def _request(command="", *, new=True, original=None):
    return {
        "version": "1.0",
        "session": {
            "new": new,
            "session_id": "session-id",
            "message_id": 0 if new else 1,
            "skill_id": "skill-id",
            "user": {"user_id": "user-id"},
            "application": {"application_id": "device-id"},
        },
        "request": {
            "command": command,
            "original_utterance": command if original is None else original,
            "type": "SimpleUtterance",
        },
    }


def test_alice_answers_activation_and_passes_followup_state_to_handler():
    async def scenario():
        handler = AsyncMock(
            side_effect=[
                AliceReply(
                    "Уточните номер группы.",
                    session_state={"period": "tomorrow"},
                ),
                AliceReply(
                    "12:25 — лекция.",
                    tts="В двенадцать двадцать пять — лекция.",
                    session_state={},
                    user_state_update={"group": "АБ-42"},
                    application_state={"group": "АБ-42"},
                ),
            ]
        )
        async with TestClient(TestServer(create_alice_app(handler))) as client:
            first_response = await client.post(
                "/alice/webhook",
                json=_request("пары завтра", original="Спроси расписание ТГУ, пары завтра"),
            )
            assert first_response.status == 200
            first = await first_response.json()
            assert first == {
                "version": "1.0",
                "response": {"text": "Уточните номер группы.", "end_session": False},
                "session_state": {"period": "tomorrow"},
            }

            followup = _request("аб 42", new=False, original="АБ-42")
            followup["state"] = {
                "session": first["session_state"],
                "user": {"old": True},
                "application": {"other": 3},
            }
            response = await client.post("/alice/webhook", json=followup)
            assert response.status == 200
            assert await response.json() == {
                "version": "1.0",
                "response": {
                    "text": "12:25 — лекция.",
                    "tts": "В двенадцать двадцать пять — лекция.",
                    "end_session": False,
                },
                "session_state": {},
                "user_state_update": {"group": "АБ-42"},
                "application_state": {"group": "АБ-42"},
            }

        activation, followup = (call.args[0] for call in handler.await_args_list)
        assert isinstance(activation, AliceRequest)
        assert activation.text == "пары завтра"
        assert activation.user_id == "user:user-id"
        assert activation.new_session is True
        assert followup.text == "АБ-42"
        assert followup.user_id == activation.user_id
        assert followup.session_id == activation.session_id == "session-id"
        assert followup.new_session is False
        assert followup.authenticated is True
        assert followup.has_application is True
        assert followup.session_state == {"period": "tomorrow"}
        assert followup.user_state == {"old": True}
        assert followup.application_state == {"other": 3}

    asyncio.run(scenario())


def test_alice_preserves_numeric_date_punctuation_in_activation_phrase():
    async def scenario():
        handler = AsyncMock(return_value="Занятий нет.")
        payload = _request(
            "пары на 25 11 2026 для группы 123456 а",
            original="Спроси расписание ТГУ, пары на 25.11.2026 для группы 123456 (а)",
        )
        async with TestClient(TestServer(create_alice_app(handler))) as client:
            response = await client.post("/alice/webhook", json=payload)
            assert response.status == 200
        assert handler.await_args.args[0].text == "пары на 25.11.2026 для группы 123456 (а)"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("identity", "expected_id", "has_application"),
    [
        ({"application": {"application_id": "device-id"}}, "application:device-id", True),
        ({"user_id": "legacy-id"}, "application:legacy-id", True),
        ({}, "session:session-id", False),
    ],
)
def test_alice_uses_device_identity_for_anonymous_requests(identity, expected_id, has_application):
    async def scenario():
        handler = AsyncMock(return_value="Занятий нет.")
        payload = _request("пары завтра")
        del payload["session"]["user"], payload["session"]["application"]
        payload["session"].update(identity)
        async with TestClient(TestServer(create_alice_app(handler))) as client:
            response = await client.post("/alice/webhook", json=payload)
            assert response.status == 200
            assert (await response.json())["response"]["text"] == "Занятий нет."
        received = handler.await_args.args[0]
        assert received.user_id == expected_id
        assert received.authenticated is False
        assert received.has_application is has_application

    asyncio.run(scenario())


def test_alice_handles_ping_welcome_help_and_exit_locally():
    async def scenario():
        handler = AsyncMock()
        async with TestClient(TestServer(create_alice_app(handler, skill_id="skill-id"))) as client:
            ping = await client.post(
                "/alice/webhook",
                json={
                    "request": {
                        "command": "",
                        "original_utterance": "ping",
                        "type": "SimpleUtterance",
                    }
                },
            )
            assert (await ping.json())["response"]["text"] == "pong"

            welcome = await client.post(
                "/alice/webhook", json=_request(original="Запусти навык расписание ТГУ")
            )
            reply = (await welcome.json())["response"]
            assert "Здравствуйте" in reply["text"]
            assert reply["end_session"] is False

            for command in ("помощь", "что ты умеешь"):
                help_request = _request(command, new=False)
                help_request["state"] = {"session": {"pending": "group"}}
                help_reply = await client.post("/alice/webhook", json=help_request)
                decoded = await help_reply.json()
                assert "расписание" in decoded["response"]["text"].casefold()
                assert decoded["session_state"] == {"pending": "group"}

            exit_reply = await client.post("/alice/webhook", json=_request("выйти", new=False))
            assert (await exit_reply.json())["response"]["end_session"] is True
        handler.assert_not_awaited()

    asyncio.run(scenario())


def test_alice_returns_client_errors_for_malformed_payload_and_other_skill():
    async def scenario():
        handler = AsyncMock()
        async with TestClient(
            TestServer(create_alice_app(handler, path="/test", skill_id="skill-id"))
        ) as client:
            wrong_method = await client.get("/test")
            assert wrong_method.status == 405
            invalid_json = await client.post(
                "/test", data="{", headers={"Content-Type": "application/json"}
            )
            assert invalid_json.status == 400
            invalid_envelope = await client.post("/test", json={"session": {}, "request": []})
            assert invalid_envelope.status == 400
            missing_session = await client.post("/test", json={"request": _request()["request"]})
            assert missing_session.status == 400
            other_skill_request = _request("пары завтра")
            other_skill_request["session"]["skill_id"] = "another-skill"
            other_skill_reply = await client.post("/test", json=other_skill_request)
            assert other_skill_reply.status == 403
        handler.assert_not_awaited()

    asyncio.run(scenario())


def test_alice_limits_text_and_tts_and_removes_tags():
    async def scenario():
        handler = AsyncMock(
            return_value=AliceReply(
                "<b>Первая пара</b>\x00\n" + "лекция " * 200,
                tts='<speaker audio="invalid">' + "Занятие. " * 200,
            ),
        )
        async with TestClient(TestServer(create_alice_app(handler))) as client:
            result = await client.post("/alice/webhook", json=_request("расписание"))
            assert result.status == 200
            response = (await result.json())["response"]
        assert response["text"].startswith("Первая пара\n")
        assert response["tts"].startswith("Занятие. ")
        assert len(response["text"]) <= 1024
        assert len(response["tts"]) <= 1024

    asyncio.run(scenario())


def test_alice_times_out_slow_handler_and_preserves_state():
    async def scenario():
        async def slow_handler(_):
            await asyncio.Event().wait()

        app = create_alice_app(slow_handler, reply_timeout=0.01)
        async with TestClient(TestServer(app)) as client:
            request = _request("а завтра", new=False)
            request["state"] = {"session": {"period": "today"}}
            result = await client.post("/alice/webhook", json=request)
            assert result.status == 200
            reply = await result.json()
        assert reply["response"]["end_session"] is False
        assert "повторите запрос" in reply["response"]["text"]
        assert reply["session_state"] == {"period": "today"}

    asyncio.run(scenario())
