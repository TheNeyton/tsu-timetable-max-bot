from datetime import date
from typing import TypeVar
from urllib.parse import quote

import httpx
from pydantic import TypeAdapter, ValidationError

from tsu_max_bot.timetable.models import (
    Audience,
    Building,
    Faculty,
    Group,
    Professor,
    Schedule,
)

BASE_URL = "https://intime.tsu.ru/api/web/v1/"
T = TypeVar("T")


class TimetableError(Exception):
    pass


class TimetableApiError(TimetableError):
    def __init__(self, path: str, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Timetable API returned HTTP {status_code} for {path}")


class TimetableConnectionError(TimetableError):
    pass


class TimetableResponseError(TimetableError):
    pass


class TimetableClient:
    """The caller owns the HTTP client and closes it after use."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str = BASE_URL,
        timeout: float = 15.0,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout = timeout

    async def get_faculties(self) -> list[Faculty]:
        return await self._get("faculties", TypeAdapter(list[Faculty]))

    async def get_groups(self, faculty_id: str) -> list[Group]:
        path = f"faculties/{quote(faculty_id, safe='')}/groups"
        return await self._get(path, TypeAdapter(list[Group]))

    async def get_professors(self) -> list[Professor]:
        return await self._get("professors", TypeAdapter(list[Professor]))

    async def get_buildings(self) -> list[Building]:
        return await self._get("buildings", TypeAdapter(list[Building]))

    async def get_audiences(self, building_id: str) -> list[Audience]:
        path = f"buildings/{quote(building_id, safe='')}/audiences"
        return await self._get(path, TypeAdapter(list[Audience]))

    async def get_group_schedule(self, group_id: str, date_from: date, date_to: date) -> Schedule:
        return await self._get_schedule("group", group_id, date_from, date_to)

    async def get_professor_schedule(
        self, professor_id: str, date_from: date, date_to: date
    ) -> Schedule:
        return await self._get_schedule("professor", professor_id, date_from, date_to)

    async def get_audience_schedule(
        self, audience_id: str, date_from: date, date_to: date
    ) -> Schedule:
        return await self._get_schedule("audience", audience_id, date_from, date_to)

    async def _get_schedule(
        self, kind: str, entity_id: str, date_from: date, date_to: date
    ) -> Schedule:
        if date_from > date_to:
            raise ValueError("date_from must not be after date_to")
        params = {
            "id": entity_id,
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
        }
        return await self._get(f"schedule/{kind}", TypeAdapter(Schedule), params)

    async def _get(
        self, path: str, adapter: TypeAdapter[T], params: dict[str, str] | None = None
    ) -> T:
        try:
            response = await self._client.get(
                self._base_url + path, params=params, timeout=self._timeout
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TimetableApiError(path, exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise TimetableConnectionError(f"Could not reach timetable API: {path}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise TimetableResponseError(f"Timetable API returned invalid JSON: {path}") from exc

        try:
            return adapter.validate_python(data)
        except ValidationError as exc:
            raise TimetableResponseError(
                f"Timetable API returned an unexpected response: {path}"
            ) from exc
