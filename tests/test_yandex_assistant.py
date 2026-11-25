import asyncio
import json
import logging
from datetime import date

import httpx
import pytest

from tsu_max_bot.schedule.query import ScheduleTarget, parse_schedule_query
from tsu_max_bot.yandex_assistant import YandexAssistant

_MESSAGE = "Подскажите, к какому времени Данилюк Елене Юрьевне в университет в среду?"


def _rewrite(handler, text=_MESSAGE, **kwargs):
    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            assistant = YandexAssistant(http, api_key="test-secret", folder_id="folder", **kwargs)
            return await assistant.rewrite(text)

    return asyncio.run(run())


def _function_call(arguments, **fields):
    return {
        "type": "function_call",
        "name": "normalize_schedule_query",
        "call_id": "call-test",
        "status": "completed",
        "arguments": arguments,
        **fields,
    }


def test_responses_api_rewrites_to_an_input_for_the_timetable_parser():
    expected = "Расписание на среду преподавателя Данилюк Елена Юрьевна"

    def handler(request):
        assert request.method == "POST"
        assert str(request.url) == "https://ai.api.cloud.yandex.net/v1/responses"
        assert request.headers["authorization"] == "Api-Key test-secret"
        assert request.headers["openai-project"] == "folder"
        assert request.extensions["timeout"]["read"] == 6.0
        payload = json.loads(request.content)
        assert payload["model"] == "gpt://folder/yandexgpt-5-pro"
        assert payload["store"] is False
        assert payload["input"] == _MESSAGE
        assert "previous_response_id" not in payload
        assert len(payload["tools"]) == 1
        assert payload["tools"][0]["name"] == payload["tool_choice"]["name"]
        assert payload["parallel_tool_calls"] is False
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [_function_call(json.dumps({"query": expected}))],
            },
        )

    result = _rewrite(handler)

    assert result == expected
    query = parse_schedule_query(result, date(2026, 11, 2))
    assert query is not None
    assert query.date_from == date(2026, 11, 4)
    assert query.target == ScheduleTarget("teacher", "Данилюк Елена Юрьевна")


@pytest.mark.parametrize(
    "output",
    [
        [_function_call('{"query":""}')],
        [_function_call('{"query":"Сегодня в 10:20 физика"}')],
        [_function_call('{"query":42}')],
        [_function_call('{"query":"Расписание на сегодня","answer":"Пара была отменена"}')],
        [_function_call('{"query":"Расписание на сегодня"}', name="unknown_tool")],
        [_function_call("broken-json")],
        [_function_call('{"query":"Расписание на сегодня"}')] * 2,
        [{"type": "message", "content": [{"type": "output_text", "text": "Расписание завтра"}]}],
    ],
)
def test_unrelated_or_untrusted_model_output_is_not_used(output):
    def handler(request):
        return httpx.Response(200, json={"status": "completed", "output": output})

    assert _rewrite(handler) is None


def test_incomplete_model_response_is_not_used():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "status": "incomplete",
                "output": [_function_call('{"query":"Расписание на сегодня"}')],
            },
        )

    assert _rewrite(handler) is None


def test_provider_error_falls_back_without_logging_key_or_conversation(caplog):
    def handler(request):
        return httpx.Response(503, text=f"debug: test-secret {_MESSAGE}")

    with caplog.at_level(logging.WARNING):
        assert _rewrite(handler) is None

    assert "503" in caplog.text
    assert "test-secret" not in caplog.text
    assert _MESSAGE not in caplog.text


def test_network_timeout_falls_back():
    def handler(request):
        raise httpx.ReadTimeout("Timed out", request=request)

    assert _rewrite(handler) is None


def test_blank_input_does_not_reach_provider():
    def handler(request):
        pytest.fail("No request is needed for blank input")

    assert _rewrite(handler, " \n\t ") is None
