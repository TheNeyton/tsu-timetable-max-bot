import asyncio
import json
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from tsu_max_bot.schedule.lessons import answer_schedule
from tsu_max_bot.schedule.query import ScheduleQuery, ScheduleTarget
from tsu_max_bot.timetable import TimetableApiError, TimetableClient

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "timetable.json").read_text(encoding="utf-8")
)
MONDAY = date(2026, 11, 2)
TUESDAY = date(2026, 11, 3)
GROUP = ScheduleTarget(kind="group", name="932521")
TEACHER = ScheduleTarget(kind="teacher", name="Данилюк Елена Юрьевна")


def _answer(query, now, handler):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await answer_schedule(TimetableClient(http), query, now, target_id="selected-id")

    return asyncio.run(run())


def test_group_day_uses_tomsk_times_and_leaves_out_empty_slots():
    def handler(request):
        assert request.url.path.endswith("/schedule/group")
        assert dict(request.url.params) == {
            "id": "selected-id",
            "dateFrom": "2026-11-02",
            "dateTo": "2026-11-02",
        }
        return httpx.Response(200, json=FIXTURES["schedule/group"])

    query = ScheduleQuery(MONDAY, MONDAY, GROUP)
    result = _answer(query, datetime(2026, 11, 2, tzinfo=UTC), handler)

    assert "2 ноября" in result
    assert "3 ноября" not in result
    assert "08:45–10:20" in result
    assert "10:35–12:10" in result
    assert "12:25" not in result
    assert result.index("Базы данных") < result.index("Математический анализ")
    assert "932521 (б)" in result
    assert "Салимзянова Дарья Дмитриевна" in result
    assert "103б" in result


def test_teacher_period_uses_teacher_endpoint_and_lists_groups():
    def handler(request):
        assert request.url.path.endswith("/schedule/professor")
        assert dict(request.url.params) == {
            "id": "selected-id",
            "dateFrom": "2026-11-02",
            "dateTo": "2026-11-03",
        }
        return httpx.Response(200, json=FIXTURES["schedule/professor"])

    query = ScheduleQuery(MONDAY, TUESDAY, TEACHER)
    result = _answer(query, datetime(2026, 11, 2, tzinfo=UTC), handler)

    assert TEACHER.name in result
    assert "Линейная алгебра и аналитическая геометрия" in result
    assert "932421 (а)" in result
    assert "932422 (а)" in result


@pytest.mark.parametrize(
    ("now", "expected_from", "expected_title", "expected_time"),
    [
        (datetime(2026, 11, 2, 3, tzinfo=UTC), "2026-11-02", "Математический анализ", "10:35"),
        (datetime(2026, 11, 2, 3, 35, tzinfo=UTC), "2026-11-02", "Математический анализ", "10:35"),
        (datetime(2026, 11, 2, 18, tzinfo=UTC), "2026-11-03", "Базы данных", "08:45"),
    ],
)
def test_next_lesson_uses_current_tomsk_date_and_start_time(
    now, expected_from, expected_title, expected_time
):
    def handler(request):
        assert request.url.params["dateFrom"] == expected_from
        assert request.url.params["dateTo"] == "2026-11-03"
        return httpx.Response(200, json=FIXTURES["schedule/group"])

    query = ScheduleQuery(MONDAY, TUESDAY, GROUP, next_lesson=True)
    result = _answer(query, now, handler)

    assert expected_title in result
    assert expected_time in result
    if expected_from == "2026-11-03":
        assert "3 ноября" in result
        assert "Онлайн" in result
    else:
        assert "2 ноября" in result
        assert "Базы данных" not in result


def test_next_lesson_respects_the_selected_period_when_it_is_in_the_past():
    def handler(request):
        pytest.fail("A past period cannot contain an upcoming lesson")

    query = ScheduleQuery(MONDAY, MONDAY, GROUP, next_lesson=True)
    result = _answer(query, datetime(2026, 11, 3, tzinfo=UTC), handler)

    assert "2 ноября" in result
    assert "нет" in result.casefold()


def test_next_lesson_shows_simultaneous_subgroup_lessons():
    schedule = deepcopy(FIXTURES["schedule/group"])
    first, second, _ = schedule["grid"][1]["lessons"]
    second.update(starts=first["starts"], ends=first["ends"])
    query = ScheduleQuery(TUESDAY, TUESDAY, GROUP, next_lesson=True)
    result = _answer(
        query,
        datetime(2026, 11, 3, tzinfo=UTC),
        lambda request: httpx.Response(200, json=schedule),
    )

    assert "Базы данных" in result
    assert "Элективные дисциплины" in result
    assert "932521 (Ф)" in result
    assert "12:25" not in result


def test_schedule_reports_an_empty_day():
    query = ScheduleQuery(TUESDAY, TUESDAY, TEACHER)
    result = _answer(
        query,
        datetime(2026, 11, 2, tzinfo=UTC),
        lambda request: httpx.Response(200, json=FIXTURES["schedule/professor"]),
    )

    assert "3 ноября" in result
    assert "Занятий нет" in result


def test_timetable_api_errors_are_available_to_the_caller():
    query = ScheduleQuery(MONDAY, MONDAY, GROUP)

    with pytest.raises(TimetableApiError) as caught:
        _answer(query, datetime(2026, 11, 2, tzinfo=UTC), lambda request: httpx.Response(503))

    assert caught.value.status_code == 503
