import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal


@dataclass(frozen=True)
class ScheduleTarget:
    kind: Literal["group", "teacher"]
    name: str


@dataclass(frozen=True)
class ScheduleQuery:
    date_from: date
    date_to: date
    target: ScheduleTarget | None = None
    next_lesson: bool = False


class QueryError(ValueError):
    """A schedule request that needs correction before it can be answered."""


_MONTHS = {
    name: number
    for number, name in enumerate(
        (
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
        ),
        1,
    )
}
_MONTH_NAMES = {
    word: number
    for number, forms in enumerate(
        (
            "январь январе",
            "февраль феврале",
            "март марте",
            "апрель апреле",
            "май мае",
            "июнь июне",
            "июль июле",
            "август августе",
            "сентябрь сентябре",
            "октябрь октябре",
            "ноябрь ноябре",
            "декабрь декабре",
        ),
        1,
    )
    for word in forms.split()
}
_WEEKDAYS = {
    word: number
    for number, forms in enumerate(
        (
            "понедельник понедельника понедельнику",
            "вторник вторника вторнику",
            "среда среды среду среде",
            "четверг четверга четвергу",
            "пятница пятницы пятницу пятнице",
            "суббота субботы субботу субботе",
            "воскресенье воскресенья воскресенью",
        ),
    )
    for word in forms.split()
}
_RELATIVE_DAYS = {"позавчера": -2, "вчера": -1, "сегодня": 0, "завтра": 1, "послезавтра": 2}
_SMALL_NUMBERS = {
    word: number
    for number, forms in enumerate(
        (
            "ноль нуль",
            "один одна одну",
            "два две",
            "три",
            "четыре",
            "пять",
            "шесть",
            "семь",
            "восемь",
            "девять",
            "десять",
            "одиннадцать",
            "двенадцать",
            "тринадцать",
            "четырнадцать",
            "пятнадцать",
            "шестнадцать",
            "семнадцать",
            "восемнадцать",
            "девятнадцать",
        ),
    )
    for word in forms.split()
}
_TENS = {
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
    "шестьдесят": 60,
    "семьдесят": 70,
    "восемьдесят": 80,
    "девяносто": 90,
}
_HUNDREDS = {
    "сто": 100,
    "двести": 200,
    "триста": 300,
    "четыреста": 400,
    "пятьсот": 500,
    "шестьсот": 600,
    "семьсот": 700,
    "восемьсот": 800,
    "девятьсот": 900,
}
_ORDINALS = {
    word: number
    for number, stem in enumerate(
        (
            "перв",
            "втор",
            "трет",
            "четверт",
            "пят",
            "шест",
            "седьм",
            "восьм",
            "девят",
            "десят",
            "одиннадцат",
            "двенадцат",
            "тринадцат",
            "четырнадцат",
            "пятнадцат",
            "шестнадцат",
            "семнадцат",
            "восемнадцат",
            "девятнадцат",
            "двадцат",
        ),
        1,
    )
    for word in (stem + "ое", stem + "ого")
}
_ORDINALS.update({"третье": 3, "третьего": 3, "тридцатое": 30, "тридцатого": 30})
_WRITTEN_NUMBERS = _SMALL_NUMBERS | _TENS | _ORDINALS

_DAY_WORD = "|".join(_WRITTEN_NUMBERS)
_DAY = (
    rf"(?:[0-9]{{1,2}}(?:\s*[-‑]\s*(?:е|го))?"
    rf"|(?:двадцать|тридцать)\s+(?:{_DAY_WORD})|{_DAY_WORD})"
)
_MONTH = "|".join(_MONTHS)
_WEEKDAY = "|".join(_WEEKDAYS)
_RELATIVE_DAY = "|".join(_RELATIVE_DAYS)
_PREPOSITION = r"(?:(?:на|в|во)\s+)?"
_ISO_DATE = r"[0-9]{4}\s*-\s*[0-9]{1,2}\s*-\s*[0-9]{1,2}"
_NUMERIC_DATE = r"[0-9]{1,2}\s*[./]\s*[0-9]{1,2}(?:\s*[./]\s*[0-9]{2,4})?"
_NAMED_DATE = rf"(?:{_DAY})\s+(?:{_MONTH})(?!\w)(?:\s+[0-9]{{4}}(?:\s+года)?(?!\w))?"
_FULL_DATE = rf"(?:{_ISO_DATE}|{_NUMERIC_DATE}|{_NAMED_DATE}|{_RELATIVE_DAY}|{_WEEKDAY})"
_RANGE_DATE = rf"(?:{_FULL_DATE}|{_DAY})"
_RANGE = re.compile(
    rf"(?<!\w)(?:с\s+|на\s+)?(?P<start>{_RANGE_DATE})(?!\w)"
    rf"(?:\s+(?:по|до)\s+|\s*[-–—]\s*)(?P<end>{_RANGE_DATE})(?!\w)",
    re.IGNORECASE,
)
_INCOMPLETE_RANGE = re.compile(rf"\bс\s+{_RANGE_DATE}\s+(?:по|до)\b", re.IGNORECASE)
_SINGLE_DATE = re.compile(
    rf"(?<!\w)(?:{_PREPOSITION}(?P<full>{_FULL_DATE})|на\s+(?P<day>{_DAY}))(?!\w)",
    re.IGNORECASE,
)
_RELATIVE_OFFSET = re.compile(
    rf"\b(?P<direction>через|за)\s+(?:(?P<count>[0-9]{{1,3}}|{_DAY_WORD})\s+)?"
    r"(?P<unit>день|дня|дней|неделю|недели|недель)(?P<ago>\s+назад|\s+до\s+этого)?\b",
    re.IGNORECASE,
)
_ADJACENT_DAY = re.compile(
    r"\b(?:на\s+)?(?P<direction>следующий|предыдущий)\s+день\b",
    re.IGNORECASE,
)
_PERIOD = re.compile(
    r"\b(?:на|в|за)\s+"
    r"(?:(?P<which>эт(?:ой|у|от)|текущ(?:ей|ую|ий)|следующ(?:ей|ую|ий)|прошл(?:ой|ую|ый))\s+)?"
    r"(?P<unit>недел(?:ю|е)|месяц(?:е)?)\b",
    re.IGNORECASE,
)
_CALENDAR_MONTH = re.compile(
    rf"\b(?:за|на|в)\s+(?P<month>{'|'.join(_MONTH_NAMES)})\b"
    r"(?:\s+(?P<year>[0-9]{4})(?:\s+года)?\b)?",
    re.IGNORECASE,
)
_SCHEDULE = re.compile(
    r"\b(?:расписани[еяюи]|парами|пар(?:а|ы|у|е|ой|ах)?|заняти(?:е|й|я|ях)|урок(?:и|ов)?)\b",
    re.IGNORECASE,
)
_NEXT_LESSON = re.compile(
    r"\b(?:(?:ближайш|следующ)(?:ая|ую|ей)\s+пар[ауы]"
    r"|(?:ближайш|следующ)(?:ее|его)\s+заняти[ея]"
    r"|(?:ближайш|следующ)(?:ий|его)\s+урок(?:а)?"
    r"|в\s+следующий\s+раз\s+(?:(?:на|у\s+(?:меня|нас))\s+)?(?:пар[ауы]|заняти[ея]|урок))\b",
    re.IGNORECASE,
)
_FOLLOW_UP_START = re.compile(r"^(?:ну\s+)?(?:а|и|тогда|теперь)\b", re.IGNORECASE)
_FOLLOW_UP_NEXT = re.compile(r"(?:когда\s+)?(?:следующая|ближайшая)", re.IGNORECASE)
_DATE_REQUEST_REMAINDER = re.compile(
    r"(?:покажи(?:те)?|скажи(?:те)?|(?:а\s+)?что(?:\s+у\s+(?:меня|нас)|\s+насчет)?"
    r"|есть\s+ли|а|и|тогда|теперь)?",
    re.IGNORECASE,
)
_TARGET = re.compile(
    r"\b(?:(?P<group>групп[ауые])|(?P<teacher>преподавател(?:ь|я|ю|е)|профессор[ауе]?))\b",
    re.IGNORECASE,
)
_TARGET_TAIL = re.compile(
    r"\s+(?:покажи(?:те)?|скажи(?:те)?|пожалуйста|как(?:ие|ое|ая|ую)|когда|во\s+сколько|"
    r"(?:есть|будут|будет)\s+ли|(?:ближайш|следующ)(?:ая|ую|ей|ее|его|ий))\b",
    re.IGNORECASE,
)
_SELF_REFERENCE = r"(?:меня|нас|себя)"
_OWN_GROUP = re.compile(rf"\bу\s+{_SELF_REFERENCE}\b", re.IGNORECASE)
_AT = re.compile(rf"\bу\s+(?!{_SELF_REFERENCE}\b)(?=[\w«\"])", re.IGNORECASE)
_GROUP_NUMBER = re.compile(r"(?<!\w)[0-9]{4,10}(?:\s*\(\s*[а-яёa-z]\s*\))?(?!\w)", re.IGNORECASE)
_GROUP_SUFFIX = re.compile(r"\s*\(\s*[а-яёa-z]\s*\)$", re.IGNORECASE)
_INITIAL = re.compile(r"(?<!\w)[а-яёa-z]\.$", re.IGNORECASE)
_PUNCTUATION = ' ,?!:;«»"'
_NEXT_LOOKAHEAD = timedelta(days=13)
_NORMALIZE_YO = str.maketrans("Ёё", "Ее")
_COMMANDS = {"/schedule": "расписание", "/next": "ближайшая пара"}


def _number(value: str) -> int:
    number = re.split(r"\s*[-‑]\s*", value)[0]
    if number.isdecimal():
        return int(number)
    return sum(_WRITTEN_NUMBERS[word] for word in number.split())


def _date_parts(value: str) -> tuple[int, int | None, int | None] | None:
    if re.fullmatch(_ISO_DATE, value):
        year, month, day = map(int, re.split(r"\s*-\s*", value))
        return day, month, year
    if re.fullmatch(_NUMERIC_DATE, value):
        day, month, *year_parts = re.split(r"\s*[./]\s*", value)
        year = None
        if year_parts:
            written_year = year_parts[0]
            year = int(written_year) + (2000 if len(written_year) == 2 else 0)
        return int(day), int(month), year
    named_date = re.fullmatch(
        rf"(?P<day>{_DAY})\s+(?P<month>{_MONTH})(?:\s+(?P<year>[0-9]{{4}})(?:\s+года)?)?",
        value,
    )
    if named_date is not None:
        year = named_date["year"]
        return _number(named_date["day"]), _MONTHS[named_date["month"]], int(year) if year else None
    if re.fullmatch(_DAY, value):
        return _number(value), None, None
    return None


def _make_date(day: int, month: int, year: int) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise QueryError("Укажите существующую дату, например 5 декабря.") from exc


def _calendar_date(value: str, anchor: date, today: date) -> date:
    if value in _RELATIVE_DAYS:
        return today + timedelta(days=_RELATIVE_DAYS[value])
    if value in _WEEKDAYS:
        return anchor + timedelta(days=(_WEEKDAYS[value] - anchor.weekday()) % 7)
    parts = _date_parts(value)
    if parts is None:
        raise QueryError("Укажите дату, например 5 декабря.")
    day, month, year = parts
    return _make_date(
        day,
        anchor.month if month is None else month,
        anchor.year if year is None else year,
    )


def _range_dates(start_text: str, end_text: str, anchor: date, today: date) -> tuple[date, date]:
    start_parts, end_parts = _date_parts(start_text), _date_parts(end_text)
    if start_parts is None or end_parts is None:
        start = _calendar_date(start_text, anchor, today)
        end = _calendar_date(end_text, start if end_text in _WEEKDAYS else anchor, today)
        return start, end

    start_day, start_month, start_year = start_parts
    end_day, end_month, end_year = end_parts
    start_month = start_month if start_month is not None else end_month
    start_month = anchor.month if start_month is None else start_month
    end_month = start_month if end_month is None else end_month
    rolls_over = end_month < start_month
    if start_year is None:
        start_year = anchor.year if end_year is None else end_year - rolls_over
    if end_year is None:
        end_year = start_year + rolls_over
    return _make_date(start_day, start_month, start_year), _make_date(end_day, end_month, end_year)


def _period_dates(which: str, unit: str, anchor: date) -> tuple[date, date]:
    offset = -1 if which.startswith("прошл") else int(which.startswith("следующ"))
    if unit.startswith("недел"):
        start = anchor
        if which or unit == "неделе":
            start += timedelta(days=offset * 7 - anchor.weekday())
        return start, start + timedelta(days=6)
    year, month = divmod(anchor.year * 12 + anchor.month - 1 + offset, 12)
    return _month_dates(year, month + 1)


def _month_dates(year: int, month: int) -> tuple[date, date]:
    return _make_date(1, month, year), date(year, month, monthrange(year, month)[1])


def _find_date_expression(text: str) -> re.Match[str] | None:
    single = _SINGLE_DATE.search(text)
    interval = _RANGE.search(text)
    # An ISO date also contains two day-sized numbers separated by a dash.
    if interval is not None and (single is None or interval.start() <= single.start()):
        return interval
    for pattern in (_INCOMPLETE_RANGE, _RELATIVE_OFFSET, _ADJACENT_DAY, _PERIOD, _CALENDAR_MONTH):
        match = pattern.search(text)
        if match is not None:
            return match
    return single


def _date_window(match: re.Match[str], anchor: date, today: date) -> tuple[date, date]:
    parts = {name: value.lower() if value else "" for name, value in match.groupdict().items()}
    if match.re is _RANGE:
        start, end = _range_dates(parts["start"], parts["end"], anchor, today)
        if start > end:
            raise QueryError("Начало интервала должно быть раньше окончания или совпадать с ним.")
        return start, end
    if match.re is _INCOMPLETE_RANGE:
        raise QueryError("Укажите обе даты интервала, например с 3 по 5 декабря.")
    if match.re is _RELATIVE_OFFSET:
        distance = _number(parts["count"]) if parts["count"] else 1
        if parts["unit"].startswith("недел"):
            distance *= 7
        if parts["ago"] or parts["direction"] == "за":
            distance *= -1
        selected = anchor + timedelta(days=distance)
    elif match.re is _ADJACENT_DAY:
        selected = anchor + timedelta(days=1 if parts["direction"] == "следующий" else -1)
    elif match.re is _PERIOD:
        return _period_dates(parts["which"], parts["unit"], anchor)
    elif match.re is _CALENDAR_MONTH:
        year = int(parts["year"]) if parts["year"] else anchor.year
        return _month_dates(year, _MONTH_NAMES[parts["month"]])
    else:
        selected = _calendar_date(parts["full"] or parts["day"], anchor, today)
    return selected, selected


def _group_name(name: str) -> str:
    name = name.lstrip("№# ")
    suffix_match = _GROUP_SUFFIX.search(name)
    suffix = ""
    code = name
    if suffix_match is not None:
        suffix = " " + re.sub(r"\s+", "", suffix_match.group())
        code = name[: suffix_match.start()]
    words = code.lower().split()
    if words and all(word.isdecimal() for word in words):
        return "".join(words) + suffix

    chunks: list[str] = []
    total = last = 0
    numbers = _SMALL_NUMBERS | _TENS | _HUNDREDS
    for word in words:
        if word not in numbers:
            return name
        number = numbers[word]
        if total and (last < 20 or number >= last):
            chunks.append(str(total))
            total = 0
        if number == 0 and not total:
            chunks.append("0")
        else:
            total += number
        last = number
    if total:
        chunks.append(str(total))
    return "".join(chunks) + suffix


def _target_name(tail: str) -> str:
    end = min(
        (
            match.start()
            for match in (_SCHEDULE.search(tail), _TARGET_TAIL.search(tail))
            if match is not None
        ),
        default=len(tail),
    )
    name = tail[:end].strip(_PUNCTUATION)
    if name.endswith(".") and not _INITIAL.search(name):
        name = name[:-1].rstrip()
    return name


def _find_target(text: str) -> ScheduleTarget | None:
    marker = _TARGET.search(text)
    if marker is not None:
        name = _target_name(text[marker.end() :])
        if marker["group"]:
            name = _group_name(name)
            if not name:
                raise QueryError("Укажите номер группы.")
            return ScheduleTarget("group", name)
        if not name:
            raise QueryError("Укажите фамилию преподавателя.")
        return ScheduleTarget("teacher", name)

    at = _AT.search(text)
    if at is not None:
        name = _target_name(text[at.end() :])
        if name:
            group_name = _group_name(name)
            if _GROUP_NUMBER.fullmatch(group_name):
                return ScheduleTarget("group", group_name)
            return ScheduleTarget("teacher", name)
    group_number = _GROUP_NUMBER.search(text)
    if group_number is not None:
        return ScheduleTarget("group", _group_name(group_number.group()))
    return None


def parse_schedule_query(
    text: str,
    today: date,
    previous: ScheduleQuery | None = None,
) -> ScheduleQuery | None:
    """Recognize a Russian schedule request, using the previous query for follow-ups."""
    original = " ".join(text.split())
    if not original:
        return None
    command, separator, arguments = original.partition(" ")
    if command.lower() in _COMMANDS:
        original = _COMMANDS[command.lower()] + separator + arguments

    normalized = original.translate(_NORMALIZE_YO)
    schedule = _SCHEDULE.search(normalized) is not None
    follows = _FOLLOW_UP_START.match(normalized)
    date_expression = _find_date_expression(normalized)
    relative_day = date_expression is not None and date_expression.re is _ADJACENT_DAY
    continuation = previous if follows or not schedule or relative_day else None
    remainder = original
    if date_expression is not None:
        left, right = date_expression.span()
        remainder = (original[:left] + " " + original[right:]).strip()
    remainder = " ".join(remainder.split())
    follow_up_text = _FOLLOW_UP_START.sub("", remainder).strip(_PUNCTUATION + ".")
    next_lesson = bool(_NEXT_LESSON.search(remainder)) or (
        continuation is not None and bool(_FOLLOW_UP_NEXT.fullmatch(follow_up_text))
    )
    marked_target = (
        _TARGET.search(remainder)
        or _AT.match(follow_up_text)
        or _OWN_GROUP.fullmatch(follow_up_text)
    )
    bare_date = date_expression is not None and _DATE_REQUEST_REMAINDER.fullmatch(
        remainder.strip(_PUNCTUATION + ".").translate(_NORMALIZE_YO),
    )
    if not (
        schedule
        or next_lesson
        or bare_date
        or (marked_target and (date_expression or continuation))
    ):
        return None
    target = _find_target(remainder)
    anchor = today
    if continuation is not None:
        if target is None and not _OWN_GROUP.search(remainder):
            target = continuation.target
        anchor = continuation.date_from if continuation.next_lesson else continuation.date_to
    try:
        if date_expression is not None:
            start, end = _date_window(date_expression, anchor, today)
        elif next_lesson:
            start, end = anchor, anchor + _NEXT_LOOKAHEAD
        elif continuation is not None:
            start, end = continuation.date_from, continuation.date_to
        else:
            start = end = today
    except OverflowError as exc:
        raise QueryError("Укажите дату в допустимом диапазоне.") from exc
    return ScheduleQuery(start, end, target, next_lesson)
