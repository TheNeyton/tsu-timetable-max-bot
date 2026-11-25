import asyncio
from datetime import datetime

import httpx
import pytest
from aiohttp.test_utils import TestClient, TestServer

from tsu_max_bot.alice import AliceRequest, create_alice_app
from tsu_max_bot.schedule.alice_handler import AliceSchedule
from tsu_max_bot.schedule.lessons import TOMSK_TZ
from tsu_max_bot.schedule.service import ScheduleService
from tsu_max_bot.timetable import TimetableClient

_GROUP = {"id": "group-14301", "name": "14301", "isSubgroup": False}
_OTHER_GROUP = {"id": "group-932521", "name": "932521", "isSubgroup": False}
_NOW = datetime(2026, 11, 25, 8, tzinfo=TOMSK_TZ)


def _timetable_http(requests, *, lesson_count=1):
    def dispatch(request):
        path = request.url.path.removeprefix("/api/web/v1/")
        match path:
            case "faculties":
                return httpx.Response(200, json=[{"id": "faculty", "name": "Факультет"}])
            case "faculties/faculty/groups":
                return httpx.Response(200, json=[_GROUP, _OTHER_GROUP])
            case "schedule/group":
                params = dict(request.url.params)
                requests.append(params)
                lessons = [
                    {
                        "type": "LESSON",
                        "id": f"lesson-{index}",
                        "title": "Математический анализ и обыкновенные дифференциальные уравнения",
                        "lessonType": "LECTURE",
                        "starts": 6300,
                        "ends": 12000,
                        "lessonNumber": index + 1,
                        "groups": [],
                    }
                    for index in range(lesson_count)
                ]
                return httpx.Response(
                    200,
                    json={"grid": [{"date": params["dateFrom"], "lessons": lessons}]},
                )
            case _:
                raise AssertionError(f"Unexpected timetable request {request.url}")

    return httpx.AsyncClient(transport=httpx.MockTransport(dispatch))


def _handler(http):
    return AliceSchedule(ScheduleService(TimetableClient(http), clock=lambda: _NOW))


def _request(text, **kwargs):
    return AliceRequest(text, "user", "session", new_session=False, **kwargs)


def test_alice_webhook_reuses_group_and_date_on_a_follow_up():
    async def scenario():
        requests = []
        async with (
            _timetable_http(requests) as http,
            TestClient(TestServer(create_alice_app(_handler(http)))) as client,
        ):
            identity = {"session_id": "session", "user": {"user_id": "account"}}

            async def speak(text, *, new=False, state=None):
                response = await client.post(
                    "/alice/webhook",
                    json={
                        "version": "1.0",
                        "session": dict(identity, new=new),
                        "request": {
                            "type": "SimpleUtterance",
                            "command": text,
                            "original_utterance": text,
                        },
                        "state": state or {},
                    },
                )
                assert response.status == 200
                return await response.json()

            choice = await speak("Моя группа 14301", new=True)
            first = await speak(
                "Какие пары 26.11.2026?",
                new=True,
                state={"user": choice["user_state_update"]},
            )
            follow_up = await speak(
                "А на следующий день?",
                state={"session": first["session_state"]},
            )

            assert "26 ноября" in first["response"]["text"]
            assert "27 ноября" in follow_up["response"]["text"]
            assert "Группа 14301" in follow_up["response"]["text"]
            assert requests == [
                {"id": "group-14301", "dateFrom": "2026-11-26", "dateTo": "2026-11-26"},
                {"id": "group-14301", "dateFrom": "2026-11-27", "dateTo": "2026-11-27"},
            ]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("authenticated", "has_application", "scope"),
    [(True, True, "user"), (False, True, "application"), (False, False, "session")],
)
def test_alice_remembers_group_in_available_preference_scope(authenticated, has_application, scope):
    async def scenario():
        requests = []
        async with _timetable_http(requests) as http:
            handler = _handler(http)
            identity = {"authenticated": authenticated, "has_application": has_application}
            saved = await handler(
                _request("Запомни группу 14301", application_state={"other": 1}, **identity),
            )
            assert "Группа 14301 сохранена" in saved.text
            assert (saved.user_state_update is not None) == (scope == "user")
            assert (saved.application_state is not None) == (scope == "application")

            if scope == "user":
                state = {"user_state": saved.user_state_update}
            elif scope == "application":
                assert saved.application_state["other"] == 1
                state = {"application_state": saved.application_state}
            else:
                state = {"session_state": saved.session_state}
            answer = await handler(_request("Какие пары завтра?", **identity, **state))
            assert "Группа 14301" in answer.text
            assert requests == [
                {"id": "group-14301", "dateFrom": "2026-11-26", "dateTo": "2026-11-26"},
            ]

    asyncio.run(scenario())


def test_group_change_accepts_spoken_number_and_discards_previous_schedule():
    async def scenario():
        requests = []
        async with _timetable_http(requests) as http:
            handler = _handler(http)
            first = await handler(_request("Пары группы 932521 на 2 декабря"))
            prompt = await handler(_request("Сменить группу", session_state=first.session_state))
            assert "номер группы" in prompt.text
            changed = await handler(
                _request("один четыре три ноль один", session_state=prompt.session_state),
            )
            assert "Группа 14301 сохранена" in changed.text
            next_day = await handler(
                _request("А на следующий день?", session_state=changed.session_state),
            )
            assert "Группа 14301" in next_day.text
            assert requests[-1] == {
                "id": "group-14301",
                "dateFrom": "2026-11-26",
                "dateTo": "2026-11-26",
            }

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ("Расписание на 31 февраля", "дату"),
        ("Моя группа 99999", "не найдена"),
        ("А какая завтра погода?", "Какие пары завтра?"),
    ],
)
def test_alice_keeps_session_context_if_an_utterance_does_not_answer_schedule(command, message):
    async def scenario():
        async with _timetable_http([]) as http:
            handler = _handler(http)
            first = await handler(_request("Пары группы 14301 на 26 ноября"))
            trouble = await handler(_request(command, session_state=first.session_state))
            assert message in trouble.text
            assert trouble.session_state == first.session_state

    asyncio.run(scenario())


def test_alice_asks_for_group_before_an_unqualified_schedule_request():
    async def scenario():
        requests = []
        async with _timetable_http(requests) as http:
            missing_group = await _handler(http)(_request("Какие пары завтра?"))
            assert "Моя группа" in missing_group.text
            assert not requests

    asyncio.run(scenario())


def test_alice_answers_the_pending_date_after_asking_for_the_group():
    async def scenario():
        requests = []
        async with _timetable_http(requests) as http:
            handler = _handler(http)
            start = await handler(_request("Какие пары 27.11.2026?"))
            answer = await handler(_request("14301", session_state=start.session_state))

        assert "27 ноября" in answer.text
        assert requests == [
            {"id": "group-14301", "dateFrom": "2026-11-27", "dateTo": "2026-11-27"},
        ]

    asyncio.run(scenario())


def test_long_alice_schedule_clips_between_complete_lessons_and_explains_how_to_narrow():
    async def scenario():
        async with _timetable_http([], lesson_count=30) as http:
            answer = await _handler(http)(_request("Пары группы 14301 на неделю"))

        assert len(answer.text) <= 1024
        assert "Укажите более короткий период" in answer.text
        lessons = answer.text.split("\n\n")[1].splitlines()[1:]
        assert lessons
        assert all(line.endswith("Лекция.") for line in lessons)

    asyncio.run(scenario())
