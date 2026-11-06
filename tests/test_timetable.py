import asyncio
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from tsu_max_bot.timetable import (
    Audience,
    Building,
    EmptySlot,
    Faculty,
    Group,
    Lesson,
    Professor,
    Schedule,
    TimetableApiError,
    TimetableClient,
    TimetableConnectionError,
    TimetableResponseError,
)

FACULTY_ID = "0bbf1b29-84ec-11e4-be9d-08606ee61ec5"
BUILDING_ID = "b8ed2551-c1ad-11ea-8117-005056bc52bb"
DATE_FROM = date(2026, 11, 2)
DATE_TO = date(2026, 11, 7)
FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "timetable.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize(
    ("method", "args", "path", "model"),
    [
        ("get_faculties", (), "faculties", Faculty),
        ("get_groups", (FACULTY_ID,), f"faculties/{FACULTY_ID}/groups", Group),
        ("get_professors", (), "professors", Professor),
        ("get_buildings", (), "buildings", Building),
        ("get_audiences", (BUILDING_ID,), f"buildings/{BUILDING_ID}/audiences", Audience),
        ("get_group_schedule", ("group-id", DATE_FROM, DATE_TO), "schedule/group", Schedule),
        (
            "get_professor_schedule",
            ("professor-id", DATE_FROM, DATE_TO),
            "schedule/professor",
            Schedule,
        ),
        (
            "get_audience_schedule",
            ("audience-id", DATE_FROM, DATE_TO),
            "schedule/audience",
            Schedule,
        ),
    ],
)
def test_endpoints_parse_documented_responses(method, args, path, model):
    def handler(request):
        assert request.method == "GET"
        assert str(request.url).startswith("https://intime.tsu.ru/api/web/v1/")
        assert request.url.path == f"/api/web/v1/{path}"
        assert request.extensions["timeout"]["read"] == 9.0
        if path.startswith("schedule/"):
            assert dict(request.url.params) == {
                "id": args[0],
                "dateFrom": "2026-11-02",
                "dateTo": "2026-11-07",
            }
        else:
            assert not request.url.params
        return httpx.Response(200, json=FIXTURES[path])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            result = await getattr(TimetableClient(http, timeout=9.0), method)(*args)
            if model is Schedule:
                assert isinstance(result, Schedule)
                assert result.grid[0].date == DATE_FROM
                assert len(result.grid) == len(FIXTURES[path]["grid"])
            else:
                assert all(isinstance(item, model) for item in result)
                assert result[0].id == FIXTURES[path][0]["id"]

    asyncio.run(run())


def test_schedule_preserves_empty_slots_subgroups_and_online_audiences():
    schedule = Schedule.model_validate(FIXTURES["schedule/group"])
    first_lesson = schedule.grid[0].lessons[0]
    assert isinstance(first_lesson, Lesson)
    assert first_lesson.groups[0].is_subgroup is True
    assert first_lesson.professor.full_name
    assert first_lesson.audience.building.address
    assert first_lesson.starts == 6300
    assert first_lesson.ends == 12000
    assert isinstance(schedule.grid[0].lessons[2], EmptySlot)
    online = schedule.grid[1].lessons[0].audience
    assert online.name == "Онлайн"
    assert online.id is None
    assert online.short_name is None
    assert online.building is None
    assert schedule.groups[0].faculty.name


def test_lesson_accepts_missing_professor_and_audience():
    data = dict(FIXTURES["schedule/group"]["grid"][0]["lessons"][0])
    data.update(professor=None, audience=None)
    lesson = Lesson.model_validate(data)
    assert lesson.professor is None
    assert lesson.audience is None


def test_building_accepts_null_address_and_coordinates():
    building = Building.model_validate(FIXTURES["buildings"][-1])
    assert building.address is None
    assert building.latitude is None
    assert building.longitude is None


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(503), TimetableApiError),
        (httpx.Response(200, text="<html>Unavailable</html>"), TimetableResponseError),
        (httpx.Response(200, json={"unexpected": []}), TimetableResponseError),
    ],
)
def test_api_failures_have_distinct_exceptions(response, error):
    async def run():
        transport = httpx.MockTransport(lambda request: response)
        async with httpx.AsyncClient(transport=transport) as http:
            with pytest.raises(error) as caught:
                await TimetableClient(http).get_faculties()
            assert caught.value.__cause__ is not None
            if error is TimetableApiError:
                assert caught.value.status_code == 503

    asyncio.run(run())


def test_transport_failure_is_wrapped():
    def handler(request):
        raise httpx.ReadTimeout("Timed out", request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(TimetableConnectionError) as caught:
                await TimetableClient(http).get_faculties()
            assert isinstance(caught.value.__cause__, httpx.ReadTimeout)

    asyncio.run(run())


def test_invalid_date_range_is_rejected_before_request():
    def handler(request):
        pytest.fail("Invalid dates must not trigger an API request")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(ValueError, match="date_from"):
                await TimetableClient(http).get_group_schedule("group", DATE_TO, DATE_FROM)

    asyncio.run(run())


def test_custom_base_url_without_trailing_slash():
    def handler(request):
        assert str(request.url) == "https://schedule.example/api/faculties"
        return httpx.Response(200, json=[])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            service = TimetableClient(http, base_url="https://schedule.example/api")
            assert await service.get_faculties() == []

    asyncio.run(run())
