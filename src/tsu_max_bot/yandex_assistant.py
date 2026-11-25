import asyncio
import json
import logging
import re

import httpx

DEFAULT_YANDEX_MODEL = "yandexgpt-5-pro"

_RESPONSES_URL = "https://ai.api.cloud.yandex.net/v1/responses"
_REQUEST_TIMEOUT = 6.0
_TOOL_NAME = "normalize_schedule_query"
_INSTRUCTIONS = """Преобразуй вопрос о расписании занятий ТГУ в короткий запрос к расписанию.
Передай его в аргументе query функции normalize_schedule_query.
Используй «Расписание» или «Ближайшая пара» в начале запроса.
Если это продолжение предыдущего вопроса, начни с «А Расписание» или «А ближайшая пара».
Сохраняй указанную дату или период. Относительные даты оставляй словами.
Явную группу укажи в форме «группы 932521», преподавателя в форме «преподавателя Иванов И. И.».
Пропускай группу или преподавателя, если в вопросе их нет.
Извлекай сведения только из вопроса. Ответы на вопросы даст отдельный сервис расписания.
Примеры:
«К какому времени мне в университет завтра?» → «Расписание на завтра».
«Когда в следующий раз на учёбу?» → «Ближайшая пара».
«Что у группы 932521 с третьего по пятое декабря?» → «Расписание группы 932521 с 3 по 5 декабря».
Для остальных вопросов передай пустую строку."""
_TOOL = {
    "type": "function",
    "name": _TOOL_NAME,
    "description": "Передать нормализованный запрос к расписанию ТГУ.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    },
}
_CANONICAL_QUERY = re.compile(r"(?:а\s+)?(?:расписание|ближайшая\s+пара)\b", re.IGNORECASE)

logger = logging.getLogger(__name__)


class YandexAssistant:
    """Interpret an individual utterance using the caller's HTTP client."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        folder_id: str,
        model: str = DEFAULT_YANDEX_MODEL,
    ) -> None:
        self._http = http
        self._headers = {"Authorization": f"Api-Key {api_key}", "OpenAI-Project": folder_id}
        self._model_uri = model if model.startswith("gpt://") else f"gpt://{folder_id}/{model}"

    async def rewrite(self, text: str) -> str | None:
        text = text.strip()
        if not text:
            return None

        try:
            async with asyncio.timeout(_REQUEST_TIMEOUT):
                response = await self._http.post(
                    _RESPONSES_URL,
                    headers=self._headers,
                    timeout=_REQUEST_TIMEOUT,
                    follow_redirects=False,
                    json={
                        "model": self._model_uri,
                        "input": text,
                        "instructions": _INSTRUCTIONS,
                        "store": False,
                        "temperature": 0,
                        "max_output_tokens": 128,
                        "tools": [_TOOL],
                        "tool_choice": {"type": "function", "name": _TOOL_NAME},
                        "parallel_tool_calls": False,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Yandex AI Studio вернула HTTP %s.", exc.response.status_code)
            return None
        except (httpx.RequestError, TimeoutError):
            logger.warning("Не удалось связаться с Yandex AI Studio.")
            return None

        try:
            return _extract_rewrite(response.json())
        except ValueError:
            logger.warning("Yandex AI Studio вернула некорректный ответ.")
            return None


def _extract_rewrite(payload: object) -> str | None:
    if not isinstance(payload, dict) or payload.get("status") != "completed":
        raise ValueError("Incomplete Responses API result")
    output = payload.get("output")
    if not isinstance(output, list):
        raise ValueError("Missing Responses API output")

    calls = [
        item for item in output if isinstance(item, dict) and item.get("type") == "function_call"
    ]
    if len(calls) != 1 or calls[0].get("name") != _TOOL_NAME:
        raise ValueError("Unexpected Responses API tool call")
    call = calls[0]
    raw_arguments = call.get("arguments")
    if call.get("status") != "completed" or not isinstance(raw_arguments, str):
        raise ValueError("Incomplete tool arguments")

    arguments = json.loads(raw_arguments)
    if (
        not isinstance(arguments, dict)
        or arguments.keys() != {"query"}
        or not isinstance(arguments["query"], str)
    ):
        raise ValueError("Invalid tool arguments")

    query = arguments["query"].strip()
    if not query:
        return None
    if len(query) > 256 or len(query.splitlines()) != 1 or not _CANONICAL_QUERY.match(query):
        raise ValueError("Invalid schedule rewrite")
    return query
