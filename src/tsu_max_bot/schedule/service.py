import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from time import monotonic

from tsu_max_bot.schedule.lessons import TOMSK_TZ, answer_schedule
from tsu_max_bot.schedule.query import (
    QueryError,
    ScheduleQuery,
    ScheduleTarget,
    parse_schedule_query,
)
from tsu_max_bot.timetable import Group, Professor, TimetableClient, TimetableError

logger = logging.getLogger(__name__)

UNAVAILABLE = "Расписание ТГУ временно недоступно. Попробуйте ещё раз позже."
EXAMPLE_GROUP = "862401"
EXAMPLES = (
    f"Спросите «Какие пары завтра?», «Ближайшая пара», «Расписание группы {EXAMPLE_GROUP} "
    "с 26.11.2026 по 28.11.2026» или «Расписание преподавателя Бабанов на пятницу»."
)


@dataclass(frozen=True)
class ScheduleContext:
    query: ScheduleQuery
    target_id: str

    def state(self) -> dict[str, object]:
        assert self.query.target is not None
        return {
            "from": self.query.date_from.isoformat(),
            "to": self.query.date_to.isoformat(),
            "kind": self.query.target.kind,
            "name": self.query.target.name,
            "id": self.target_id,
            "next": self.query.next_lesson,
        }

    @classmethod
    def from_state(cls, state: object) -> "ScheduleContext | None":
        if not isinstance(state, dict):
            return None
        kind = state.get("kind")
        name, target_id = state.get("name"), state.get("id")
        if kind not in ("group", "teacher") or not all(
            isinstance(value, str) and 0 < len(value) <= 256 for value in (name, target_id)
        ):
            return None
        try:
            first = date.fromisoformat(state["from"])
            last = date.fromisoformat(state["to"])
        except (KeyError, TypeError, ValueError):
            return None
        if last < first:
            return None
        query = ScheduleQuery(first, last, ScheduleTarget(kind, name), state.get("next") is True)
        return cls(query, target_id)


@dataclass(frozen=True)
class ScheduleReply:
    text: str
    context: ScheduleContext | None = None


def _group_key(name: str) -> str:
    return re.sub(r"[\s‐‑‒–—−-]+", "", name.casefold()).replace("ё", "е")


def _name_parts(name: str) -> list[str]:
    return re.findall(r"[а-яa-z-]+", name.casefold().replace("ё", "е"))


def _matches_name(query: list[str], name: list[str], *, inflected: bool = False) -> bool:
    if not query or len(query) > len(name):
        return False
    orders = (query, [query[-1], *query[:-1]]) if len(query) > 1 else (query,)
    for surname, *rest in orders:
        surnames = {surname}
        if inflected:
            surnames.update(surname.removesuffix(ending) for ending in ("а", "у", "ом", "ой"))
            if surname.endswith("ого"):
                surnames.add(surname.removesuffix("ого") + "ий")
            if surname.endswith("ой"):
                surnames.add(surname.removesuffix("ой") + "ая")
        if name[0] in surnames and all(
            given == actual or (len(given) == 1 and actual.startswith(given))
            for given, actual in zip(rest, name[1:], strict=False)
        ):
            return True
    return False


class ScheduleService:
    def __init__(
        self,
        client: TimetableClient,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(TOMSK_TZ),
        rewrite: Callable[[str], Awaitable[str | None]] | None = None,
    ) -> None:
        self._client = client
        self._clock = clock
        self._rewrite = rewrite
        self._group_cache: tuple[float, list[Group]] | None = None
        self._group_lock = asyncio.Lock()

    def parse(self, text: str, previous: ScheduleContext | None) -> ScheduleQuery | None:
        return parse_schedule_query(
            text, self._clock().date(), previous.query if previous else None
        )

    async def interpret(self, text: str, previous: ScheduleContext | None) -> ScheduleQuery | None:
        query = self.parse(text, previous)
        if query is None and self._rewrite is not None:
            rewritten = await self._rewrite(text)
            if rewritten:
                query = self.parse(rewritten, previous)
        return query

    async def resolve_group(self, name: str) -> Group:
        key = _group_key(name)
        groups = [group for group in await self._groups() if _group_key(group.name) == key]
        if not groups:
            raise QueryError(f"Группа «{name}» не найдена. Проверьте её название.")
        if len(groups) > 1:
            raise QueryError(f"В каталоге несколько групп «{name}». Уточните название группы.")
        return groups[0]

    async def _groups(self) -> list[Group]:
        async with self._group_lock:
            if self._group_cache is None or self._group_cache[0] <= monotonic():
                faculties = await self._client.get_faculties()
                async with asyncio.TaskGroup() as tasks:
                    # Return expected failures so the task group can close cleanly on cancellation.
                    requests = [tasks.create_task(self._groups_for(f.id)) for f in faculties]
                groups: dict[str, Group] = {}
                for task in requests:
                    result = task.result()
                    if isinstance(result, TimetableError):
                        raise result
                    groups.update((group.id, group) for group in result)
                self._group_cache = (monotonic() + 600, list(groups.values()))
            return self._group_cache[1]

    async def _groups_for(self, faculty_id: str) -> list[Group] | TimetableError:
        try:
            return await self._client.get_groups(faculty_id)
        except TimetableError as error:
            return error

    async def _resolve_teacher(self, name: str) -> Professor:
        professors = await self._client.get_professors()
        requested = _name_parts(name)
        matches = [
            prof for prof in professors if _matches_name(requested, _name_parts(prof.full_name))
        ]
        if not matches:
            matches = [
                prof
                for prof in professors
                if _matches_name(requested, _name_parts(prof.full_name), inflected=True)
            ]
        if not matches:
            raise QueryError(f"Преподаватель «{name}» не найден. Проверьте фамилию и имя.")
        if len(matches) > 1:
            names = ", ".join(dict.fromkeys(prof.full_name for prof in matches[:4]))
            raise QueryError(f"Нашлось несколько преподавателей. Уточните ФИО. Варианты: {names}.")
        return matches[0]

    async def answer(
        self,
        query: ScheduleQuery,
        *,
        default_group: tuple[ScheduleTarget, str] | None,
        previous: ScheduleContext | None,
        missing_group: str,
    ) -> ScheduleReply:
        try:
            target = query.target
            if target is None:
                if default_group is None:
                    return ScheduleReply(missing_group)
                target, target_id = default_group
            elif previous and target == previous.query.target:
                target_id = previous.target_id
            elif target.kind == "group":
                if default_group and _group_key(target.name) == _group_key(default_group[0].name):
                    target, target_id = default_group
                else:
                    group = await self.resolve_group(target.name)
                    target, target_id = ScheduleTarget("group", group.name), group.id
            else:
                professor = await self._resolve_teacher(target.name)
                target, target_id = ScheduleTarget("teacher", professor.full_name), professor.id

            resolved = replace(query, target=target)
            text = await answer_schedule(self._client, resolved, self._clock(), target_id=target_id)
        except QueryError as error:
            return ScheduleReply(str(error))
        except TimetableError:
            logger.exception("Не удалось получить расписание ТГУ.")
            return ScheduleReply(UNAVAILABLE)
        return ScheduleReply(text, ScheduleContext(resolved, target_id))
