import logging
import re

from tsu_max_bot.alice import AliceReply, AliceRequest
from tsu_max_bot.schedule.query import QueryError, ScheduleTarget
from tsu_max_bot.schedule.service import (
    EXAMPLE_GROUP,
    EXAMPLES,
    UNAVAILABLE,
    ScheduleContext,
    ScheduleService,
)
from tsu_max_bot.timetable import TimetableError

logger = logging.getLogger(__name__)

_GROUP_COMMAND = re.compile(
    r"(?:моя группа|запомни(?:те)? (?:мою )?группу|смен(?:ить|и|ите) группу)"
    r"(?:[\s:—-]+(?P<name>.+))?",
    re.IGNORECASE,
)
_DEFAULT_GROUP = "default_group"
_CONTEXT = "schedule_context"
_AWAIT_GROUP = "await_group"
_PENDING_QUERY = "pending_query"
_GROUP_PROMPT = f"Скажите номер группы, например {EXAMPLE_GROUP}."
_MISSING_GROUP = f"Назовите номер Вашей группы. Например, скажите «Моя группа {EXAMPLE_GROUP}»."
_SHORTER_PERIOD = (
    "Показана часть расписания. Укажите более короткий период, чтобы увидеть остальные пары."
)
_TEXT_LIMIT = 1024


def _read_group(state: dict[str, object]) -> tuple[ScheduleTarget, str] | None:
    group = state.get(_DEFAULT_GROUP)
    if not isinstance(group, dict):
        return None
    name, group_id = group.get("name"), group.get("id")
    if not all(isinstance(value, str) and 0 < len(value) <= 256 for value in (name, group_id)):
        return None
    return ScheduleTarget("group", name), group_id


def _preferred_group(request: AliceRequest) -> tuple[ScheduleTarget, str] | None:
    if request.authenticated:
        saved = _read_group(request.user_state)
    elif request.has_application:
        saved = _read_group(request.application_state)
    else:
        saved = None
    return saved or _read_group(request.session_state)


def _shorten(text: str) -> str:
    if len(text) <= _TEXT_LIMIT:
        return text
    available = _TEXT_LIMIT - len(_SHORTER_PERIOD) - 2
    last_break = text.rfind("\n", 0, available + 1)
    if last_break < 0:
        return _SHORTER_PERIOD
    shown = text[:last_break].rstrip()
    preceding, separator, final_section = shown.rpartition("\n\n")
    if separator and "\n" not in final_section:
        shown = preceding
    return f"{shown}\n\n{_SHORTER_PERIOD}"


class AliceSchedule:
    def __init__(self, schedules: ScheduleService) -> None:
        self._schedules = schedules

    async def __call__(self, request: AliceRequest) -> AliceReply:
        text = " ".join(request.text.split()).strip(' .!?«»"')
        state = request.session_state.copy()
        previous = ScheduleContext.from_state(state.get(_CONTEXT))
        command = _GROUP_COMMAND.fullmatch(text)

        try:
            if command is not None:
                name = command["name"]
                if name:
                    return await self._save_group(self._group_name(name), request, state)
                state[_AWAIT_GROUP] = True
                state.pop(_PENDING_QUERY, None)
                return AliceReply(_GROUP_PROMPT, session_state=state)

            query = self._schedules.parse(text, previous)
            if query is None:
                if state.get(_AWAIT_GROUP) is True:
                    name = self._group_name(text)
                    if any(character.isdecimal() for character in name):
                        return await self._save_group(name, request, state)
                    return AliceReply(_GROUP_PROMPT, session_state=state)
                return AliceReply(EXAMPLES, session_state=state)

            default_group = _preferred_group(request)
            if query.target is None and default_group is None:
                state[_AWAIT_GROUP] = True
                state[_PENDING_QUERY] = {
                    "from": query.date_from.isoformat(),
                    "to": query.date_to.isoformat(),
                    "next": query.next_lesson,
                }
                return AliceReply(_MISSING_GROUP, session_state=state)
            answer = await self._schedules.answer(
                query,
                default_group=default_group,
                previous=previous,
                missing_group=_MISSING_GROUP,
            )
        except QueryError as error:
            return AliceReply(str(error), session_state=state)
        except TimetableError:
            logger.exception("Не удалось получить группу ТГУ для Алисы.")
            return AliceReply(UNAVAILABLE, session_state=state)

        if answer.context is not None:
            state[_CONTEXT] = answer.context.state()
            state.pop(_AWAIT_GROUP, None)
            state.pop(_PENDING_QUERY, None)
        return AliceReply(_shorten(answer.text), session_state=state)

    def _group_name(self, text: str) -> str:
        parsed = self._schedules.parse(f"Расписание группы {text}", None)
        if parsed is None or parsed.target is None:
            raise QueryError(_GROUP_PROMPT)
        return parsed.target.name

    async def _save_group(
        self,
        name: str,
        request: AliceRequest,
        state: dict[str, object],
    ) -> AliceReply:
        group = await self._schedules.resolve_group(name)
        preference = {"name": group.name, "id": group.id}
        saved = {_DEFAULT_GROUP: preference}
        state.update(saved)
        state.pop(_AWAIT_GROUP, None)
        state.pop(_CONTEXT, None)
        pending = state.pop(_PENDING_QUERY, None)
        application_state = None
        if request.has_application and not request.authenticated:
            application_state = {**request.application_state, **saved}
        confirmation = f"Группа {group.name} сохранена."
        text = f"{confirmation} Спросите, какие пары завтра."
        if isinstance(pending, dict):
            context = ScheduleContext.from_state(
                {**pending, "kind": "group", "name": group.name, "id": group.id}
            )
            if context is not None:
                answer = await self._schedules.answer(
                    context.query,
                    default_group=None,
                    previous=context,
                    missing_group=_MISSING_GROUP,
                )
                if answer.context is not None:
                    state[_CONTEXT] = answer.context.state()
                text = _shorten(f"{confirmation}\n\n{answer.text}")
        return AliceReply(
            text,
            session_state=state,
            user_state_update=saved if request.authenticated else None,
            application_state=application_state,
        )
