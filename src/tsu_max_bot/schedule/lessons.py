from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from tsu_max_bot.schedule.query import ScheduleQuery
from tsu_max_bot.timetable import Lesson, TimetableClient

TOMSK_TZ = ZoneInfo("Asia/Tomsk")

_MONTH_NAMES = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_LESSON_TYPES = {
    "LECTURE": "Лекция",
    "PRACTICE": "Практика",
    "LABORATORY": "Лабораторная работа",
    "CONSULTATION": "Консультация",
    "EXAM": "Экзамен",
    "CREDIT": "Зачёт",
}


async def answer_schedule(
    client: TimetableClient, query: ScheduleQuery, now: datetime, *, target_id: str
) -> str:
    if query.target is None:
        raise ValueError("A schedule target must be resolved before fetching lessons")

    teacher_schedule = query.target.kind == "teacher"
    if teacher_schedule:
        subject = query.target.name
        fetch_schedule = client.get_professor_schedule
    else:
        subject = f"Группа {query.target.name}"
        fetch_schedule = client.get_group_schedule

    local_now = now.astimezone(TOMSK_TZ) if now.tzinfo else now.replace(tzinfo=TOMSK_TZ)
    first_day = max(query.date_from, local_now.date()) if query.next_lesson else query.date_from
    if first_day <= query.date_to:
        schedule = await fetch_schedule(target_id, first_day, query.date_to)
        sections = []
        for day in sorted(schedule.grid, key=lambda item: item.date):
            if not first_day <= day.date <= query.date_to:
                continue

            lessons = sorted(
                (item for item in day.lessons if isinstance(item, Lesson)),
                key=lambda lesson: _tomsk_time(lesson.starts),
            )
            if query.next_lesson and day.date == local_now.date():
                lessons = [slot for slot in lessons if _tomsk_time(slot.starts) >= local_now.time()]
            if not lessons:
                continue

            day_label = _format_date(day.date, local_now.year)
            if query.next_lesson:
                first_start = lessons[0].starts
                closest = [lesson for lesson in lessons if lesson.starts == first_start]
                heading = "Ближайшее занятие" if len(closest) == 1 else "Ближайшие занятия"
                lines = [_format_lesson(lesson, teacher_schedule) for lesson in closest]
                return "\n".join([f"{heading}. {subject}. {day_label}.", *lines])

            lines = [_format_lesson(lesson, teacher_schedule) for lesson in lessons]
            sections.append("\n".join([day_label, *lines]))
        if sections:
            return "\n\n".join([f"Расписание. {subject}.", *sections])

    period = _format_date(query.date_from, local_now.year)
    if query.date_from != query.date_to:
        period = f"С {period} по {_format_date(query.date_to, local_now.year)}"
    summary = "Предстоящих занятий нет" if query.next_lesson else "Занятий нет"
    return f"{subject}. {period}. {summary}."


def _tomsk_time(seconds: int) -> time:
    # The timetable web app formats starts and ends as Unix timestamps in Asia/Tomsk.
    return datetime.fromtimestamp(seconds, TOMSK_TZ).time()


def _format_date(day: date, current_year: int) -> str:
    label = f"{day.day} {_MONTH_NAMES[day.month - 1]}"
    return label if day.year == current_year else f"{label} {day.year} года"


def _format_lesson(lesson: Lesson, teacher_schedule: bool) -> str:
    clock = f"{_tomsk_time(lesson.starts):%H:%M}–{_tomsk_time(lesson.ends):%H:%M}"
    details = [f"{clock} — {lesson.title.strip().rstrip('.')}"]
    lesson_type = _LESSON_TYPES.get(lesson.lesson_type)
    if lesson_type:
        details.append(lesson_type)

    if teacher_schedule:
        groups = [group.name for group in lesson.groups]
        group_label = "Группа" if len(groups) == 1 else "Группы"
    else:
        groups = [group.name for group in lesson.groups if group.is_subgroup]
        group_label = "Подгруппа" if len(groups) == 1 else "Подгруппы"
        if lesson.professor is not None:
            details.append(lesson.professor.full_name)
    if groups:
        details.append(f"{group_label} {', '.join(groups)}")

    if lesson.audience is not None:
        audience = lesson.audience
        room = (audience.short_name or audience.name).strip()
        if audience.building is not None:
            room = f"Аудитория {room}, {audience.building.name}"
        details.append(room)
    return ". ".join(details) + "."
