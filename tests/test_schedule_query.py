from dataclasses import replace
from datetime import date

import pytest

from tsu_max_bot.schedule.query import (
    QueryError,
    ScheduleQuery,
    ScheduleTarget,
    parse_schedule_query,
)

TODAY = date(2026, 11, 25)


@pytest.mark.parametrize(
    ("message", "start", "end"),
    [
        ("Расписание", TODAY, TODAY),
        ("/schedule", TODAY, TODAY),
        ("Какие пары завтра?", date(2026, 11, 26), date(2026, 11, 26)),
        ("Какие у меня завтра пары?", date(2026, 11, 26), date(2026, 11, 26)),
        ("Послезавтра", date(2026, 11, 27), date(2026, 11, 27)),
        ("Расписание в понедельник", date(2026, 11, 30), date(2026, 11, 30)),
        ("Что у нас на этой неделе?", date(2026, 11, 23), date(2026, 11, 29)),
        ("На следующую неделю", date(2026, 11, 30), date(2026, 12, 6)),
        ("Пары на неделю", TODAY, date(2026, 12, 1)),
        ("Пары за декабрь", date(2026, 12, 1), date(2026, 12, 31)),
        ("Пары в феврале 2028 года", date(2028, 2, 1), date(2028, 2, 29)),
        ("Расписание на 5.12", date(2026, 12, 5), date(2026, 12, 5)),
        ("Расписание на 2026-12-05", date(2026, 12, 5), date(2026, 12, 5)),
        ("Расписание на 2026 - 12 - 05", date(2026, 12, 5), date(2026, 12, 5)),
        ("Расписание 2026-12-05 — 2026-12-06", date(2026, 12, 5), date(2026, 12, 6)),
        ("Расписание на двадцать пятое декабря", date(2026, 12, 25), date(2026, 12, 25)),
        ("Что по расписанию двадцать пятого декабря?", date(2026, 12, 25), date(2026, 12, 25)),
        ("С 3 по 5 декабря", date(2026, 12, 3), date(2026, 12, 5)),
        ("Пары 03.12–05.12.2026", date(2026, 12, 3), date(2026, 12, 5)),
        ("Расписание с понедельника по пятницу", date(2026, 11, 30), date(2026, 12, 4)),
        ("Расписание на 30 декабря — 3 января", date(2026, 12, 30), date(2027, 1, 3)),
    ],
)
def test_parses_single_dates_and_inclusive_periods(message, start, end):
    assert parse_schedule_query(message, TODAY) == ScheduleQuery(start, end)


@pytest.mark.parametrize(
    ("message", "kind", "name"),
    [
        ("Расписание группы 932521 (б) на завтра", "group", "932521 (б)"),
        ("Какие пары завтра у группы 93 25 21?", "group", "932521"),
        (
            "Расписание на завтра группы девяносто три двадцать пять двадцать один",
            "group",
            "932521",
        ),
        ("Пары 932521 завтра", "group", "932521"),
        ("Расписание преподавателя Елена Данилюк на завтра", "teacher", "Елена Данилюк"),
        ("Покажи расписание у Данилюк Е. Ю. на завтра", "teacher", "Данилюк Е. Ю."),
        ("Какие пары завтра у Салимзяновой?", "teacher", "Салимзяновой"),
    ],
)
def test_extracts_groups_and_teacher_names_on_either_side_of_date(message, kind, name):
    tomorrow = date(2026, 11, 26)
    assert parse_schedule_query(message, TODAY) == ScheduleQuery(
        tomorrow,
        tomorrow,
        ScheduleTarget(kind, name),
    )


@pytest.mark.parametrize(
    "message",
    ["Когда ближайшая пара?", "Ближайшая пара", "Когда в следующий раз на пары?", "/next"],
)
def test_nearest_lesson_starts_search_today(message):
    assert parse_schedule_query(message, TODAY) == ScheduleQuery(
        TODAY,
        date(2026, 12, 8),
        next_lesson=True,
    )


def test_next_lesson_can_be_restricted_to_an_explicit_target_and_day():
    assert parse_schedule_query("Во сколько следующая пара у Данилюк завтра?", TODAY) == (
        ScheduleQuery(
            date(2026, 11, 26),
            date(2026, 11, 26),
            ScheduleTarget("teacher", "Данилюк"),
            True,
        )
    )


def test_follow_up_uses_the_last_requested_date_and_target():
    first = parse_schedule_query("Пары преподавателя Данилюк на 10 декабря", TODAY)
    second = parse_schedule_query("А на следующий день?", TODAY, first)
    third = parse_schedule_query("А через два дня?", TODAY, second)

    target = ScheduleTarget("teacher", "Данилюк")
    assert second == ScheduleQuery(date(2026, 12, 11), date(2026, 12, 11), target)
    assert third == ScheduleQuery(date(2026, 12, 13), date(2026, 12, 13), target)


@pytest.mark.parametrize(
    ("message", "day"),
    [
        ("А сегодня?", 25),
        ("А завтра?", 26),
        ("А вчера?", 24),
        ("А послезавтра?", 27),
        ("А позавчера?", 23),
    ],
)
def test_relative_calendar_day_follow_up_uses_today_and_reuses_target(message, day):
    target = ScheduleTarget("teacher", "Бабанов")
    first = ScheduleQuery(date(2026, 12, 10), date(2026, 12, 10), target)
    expected_date = date(2026, 11, day)

    assert parse_schedule_query(message, TODAY, first) == ScheduleQuery(
        expected_date,
        expected_date,
        target,
    )


def test_follow_up_can_switch_target_and_reuse_requested_dates():
    first = parse_schedule_query("Пары преподавателя Данилюк с 10 по 12 декабря", TODAY)

    assert parse_schedule_query("А у группы 932521?", TODAY, first) == ScheduleQuery(
        date(2026, 12, 10),
        date(2026, 12, 12),
        ScheduleTarget("group", "932521"),
    )


def test_weekday_follow_up_with_after_uses_the_last_requested_day():
    first = parse_schedule_query("Пары на 10 декабря", TODAY)

    assert parse_schedule_query("А на следующий день?", TODAY, first) == ScheduleQuery(
        date(2026, 12, 11),
        date(2026, 12, 11),
    )


def test_follow_up_reuses_exact_requested_date_and_resolved_target():
    first = parse_schedule_query("Какие пары 26.11.2026?", TODAY)
    assert first == ScheduleQuery(date(2026, 11, 26), date(2026, 11, 26))
    target = ScheduleTarget("group", "14301")

    assert parse_schedule_query("А на следующий день?", TODAY, replace(first, target=target)) == (
        ScheduleQuery(date(2026, 11, 27), date(2026, 11, 27), target)
    )


def test_group_schedule_with_numeric_date_range():
    assert parse_schedule_query("Расписание группы 14301 с 26.11.2026 по 28.11.2026", TODAY) == (
        ScheduleQuery(date(2026, 11, 26), date(2026, 11, 28), ScheduleTarget("group", "14301"))
    )


def test_teacher_schedule_with_named_weekday():
    assert parse_schedule_query("Расписание преподавателя Бабанов на пятницу", TODAY) == (
        ScheduleQuery(date(2026, 11, 27), date(2026, 11, 27), ScheduleTarget("teacher", "Бабанов"))
    )


def test_new_full_request_uses_today_and_allows_saved_group_fallback():
    first = parse_schedule_query("Расписание преподавателя Данилюк на 10 декабря", TODAY)

    assert parse_schedule_query("Покажи мое расписание завтра", TODAY, first) == ScheduleQuery(
        date(2026, 11, 26),
        date(2026, 11, 26),
    )


@pytest.mark.parametrize(
    "target", [ScheduleTarget("teacher", "Бабанов"), ScheduleTarget("group", "932521")]
)
@pytest.mark.parametrize(
    "message",
    ["А какие у меня пары завтра?", "А у меня завтра?", "А у нас завтра?"],
)
def test_own_group_follow_up_resolves_tomorrow_from_today_and_uses_saved_group(message, target):
    first = ScheduleQuery(date(2026, 12, 10), date(2026, 12, 10), target)

    assert parse_schedule_query(message, TODAY, first) == ScheduleQuery(
        date(2026, 11, 26),
        date(2026, 11, 26),
    )


def test_own_group_follow_up_without_a_date_reuses_requested_period():
    first = ScheduleQuery(
        date(2026, 12, 10),
        date(2026, 12, 12),
        ScheduleTarget("teacher", "Бабанов"),
    )

    assert parse_schedule_query("А у меня?", TODAY, first) == ScheduleQuery(
        date(2026, 12, 10),
        date(2026, 12, 12),
    )


@pytest.mark.parametrize(
    "message",
    ["Привет", "Люблю среду", "Помню 31 февраля", "А как дела?", "А что Вы умеете?", ""],
)
def test_unrelated_messages_leave_schedule_handling_to_the_caller(message):
    first = ScheduleQuery(TODAY, TODAY, ScheduleTarget("teacher", "Данилюк"))
    assert parse_schedule_query(message, TODAY, first) is None


@pytest.mark.parametrize(
    ("message", "error"),
    [
        ("Пары на 31 февраля", "дат"),
        ("Пары с 6 по 3 декабря", "раньше"),
        ("Пары с 3 декабря по неизвестную дату", "интервал"),
        ("Покажи расписание преподавателя на завтра", "преподавателя"),
        ("Покажи расписание группы на завтра", "группы"),
    ],
)
def test_invalid_schedule_inputs_produce_displayable_errors(message, error):
    with pytest.raises(QueryError, match=error):
        parse_schedule_query(message, TODAY)
