import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Literal

from aiohttp import web
from pydantic import BaseModel, Field

_LOGGER = logging.getLogger(__name__)
_TEXT_LIMIT = 1024
_STATE_LIMIT = 1024
_RESPONSE_LIMIT = 5000
_DUMPS = partial(json.dumps, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
_TAG = re.compile(r"<[^<>]*>")
_WORD = re.compile(r"\w+")
_INVALID_CHAR = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]")

_WELCOME = (
    "Здравствуйте! Здесь можно узнать расписание ТГУ. "
    "Спросите, какие пары завтра, или скажите «Помощь»."
)
_HELP = (
    "Я подскажу расписание занятий в ТГУ. "
    "Скажите, например, «Какие пары завтра?» и назовите номер Вашей группы."
)
_RETRY = "Пожалуйста, повторите запрос."
_EXIT = {"пока", "до свидания", "стоп", "закончить", "выйти", "выход", "выход из навыка"}


@dataclass(frozen=True, slots=True)
class AliceRequest:
    text: str
    user_id: str
    session_id: str
    new_session: bool
    session_state: dict[str, object] = field(default_factory=dict)
    user_state: dict[str, object] = field(default_factory=dict)
    application_state: dict[str, object] = field(default_factory=dict)
    authenticated: bool = False
    has_application: bool = False


@dataclass(frozen=True, slots=True)
class AliceReply:
    text: str
    tts: str | None = None
    end_session: bool = False
    session_state: dict[str, object] | None = None
    user_state_update: dict[str, object] | None = None
    application_state: dict[str, object] | None = None


AliceHandler = Callable[[AliceRequest], Awaitable[AliceReply | str]]


class _User(BaseModel):
    user_id: str | None = None


class _Application(BaseModel):
    application_id: str | None = None


class _Session(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    new: bool
    skill_id: str | None = None
    user: _User | None = None
    application: _Application | None = None
    user_id: str | None = None


class _Utterance(BaseModel):
    type: str
    command: str = ""
    original_utterance: str = ""


class _State(BaseModel):
    session: dict[str, object] = Field(default_factory=dict)
    user: dict[str, object] = Field(default_factory=dict)
    application: dict[str, object] = Field(default_factory=dict)


class _Envelope(BaseModel):
    request: _Utterance
    session: _Session | None = None
    state: _State = Field(default_factory=_State)
    version: Literal["1.0"] | None = None


def _request_text(utterance: _Utterance, new_session: bool) -> str:
    original = utterance.original_utterance.strip()
    command = utterance.command.strip()
    if not new_session:
        return original or command

    # Yandex strips the activation phrase from command. Recover punctuation from its raw suffix.
    command_tokens = _WORD.findall(command.casefold())
    if command_tokens:
        original_tokens = list(_WORD.finditer(original))
        suffix = original_tokens[-len(command_tokens) :]
        if command_tokens == [token.group().casefold() for token in suffix]:
            return original[suffix[0].start() :]
    return command


def _builtin_reply(utterance: _Utterance, request: AliceRequest) -> AliceReply | None:
    command = (utterance.command.strip() or request.text).casefold().strip(" .!?")
    if utterance.type != "SimpleUtterance":
        return AliceReply(
            "Скажите, на какой день Вам нужно расписание.",
            session_state=request.session_state or None,
        )
    if command in _EXIT:
        return AliceReply("До свидания!", end_session=True)
    if command in {"помощь", "что ты умеешь", "что вы умеете", "что умеешь"}:
        return AliceReply(_HELP, session_state=request.session_state or None)
    if not command or command in {"привет", "здравствуйте", "добрый день"}:
        return AliceReply(_WELCOME, session_state=request.session_state or None)
    return None


def _alice_request(utterance: _Utterance, session: _Session, state: _State) -> AliceRequest:
    account_id = session.user.user_id if session.user else None
    application_id = session.application.application_id if session.application else None
    application_id = application_id or session.user_id
    if account_id:
        user_id = f"user:{account_id}"
    elif application_id:
        user_id = f"application:{application_id}"
    else:
        user_id = f"session:{session.session_id}"
    return AliceRequest(
        text=_request_text(utterance, session.new),
        user_id=user_id,
        session_id=session.session_id,
        new_session=session.new,
        session_state=state.session,
        user_state=state.user,
        application_state=state.application,
        authenticated=bool(account_id),
        has_application=bool(application_id),
    )


def _plain_text(text: str) -> str:
    text = _TAG.sub("", text)
    return _INVALID_CHAR.sub("", text).replace("\r\n", "\n").replace("\r", "\n").strip()


def _limited_text(text: str) -> str:
    if len(text) <= _TEXT_LIMIT:
        return text
    prefix = text[: _TEXT_LIMIT - 1]
    if not prefix[-1].isspace() and not text[_TEXT_LIMIT - 1].isspace():
        before_last_word = prefix.rsplit(maxsplit=1)[0]
        if len(before_last_word) >= _TEXT_LIMIT // 2:
            prefix = before_last_word
    return prefix.rstrip() + "…"


def _reply_response(reply: AliceReply) -> web.Response:
    text = _limited_text(_plain_text(reply.text))
    tts = _limited_text(" ".join(_plain_text(reply.tts or "").split()))
    response = {"text": text, "end_session": reply.end_session}
    if tts:
        response["tts"] = tts
    elif not text:
        response["text"] = _RETRY

    envelope = {"version": "1.0", "response": response}
    for name, state in (
        ("session_state", reply.session_state),
        ("user_state_update", reply.user_state_update),
        ("application_state", reply.application_state),
    ):
        if state is None:
            continue
        try:
            state_size = len(_DUMPS(state).encode())
        except (TypeError, ValueError, RecursionError):
            _LOGGER.warning("Ignoring invalid Alice reply field %s", name)
            continue
        if name != "application_state" and state_size > _STATE_LIMIT:
            _LOGGER.warning("Ignoring oversized Alice reply field %s", name)
            continue
        envelope[name] = state
        if len(_DUMPS(envelope)) > _RESPONSE_LIMIT:
            del envelope[name]
            _LOGGER.warning("Ignoring Alice reply field %s due to response size", name)
    return web.json_response(envelope, dumps=_DUMPS)


async def _call_handler(
    handler: AliceHandler, request: AliceRequest, reply_timeout: float
) -> AliceReply:
    try:
        async with asyncio.timeout(reply_timeout):
            result = await handler(request)
    except TimeoutError:
        return AliceReply(
            f"Ответ занял слишком много времени. {_RETRY}",
            session_state=request.session_state or None,
        )
    except Exception:
        _LOGGER.exception("Error while answering an Alice request")
        return AliceReply(
            f"Сейчас не получается получить расписание. {_RETRY}",
            session_state=request.session_state or None,
        )
    return AliceReply(result) if isinstance(result, str) else result


def create_alice_app(
    handler: AliceHandler,
    *,
    path: str = "/alice/webhook",
    skill_id: str | None = None,
    reply_timeout: float = 4.0,
) -> web.Application:
    """Create the HTTP application for an Alice skill using the Dialogs 1.0 protocol."""

    async def webhook(http_request: web.Request) -> web.Response:
        try:
            body = json.loads(await http_request.read())
            envelope = _Envelope.model_validate(body, strict=True)
        except (ValueError, RecursionError):
            raise web.HTTPBadRequest(text="Invalid Alice request") from None

        utterance = envelope.request
        session = envelope.session
        if skill_id is not None and session is not None and session.skill_id != skill_id:
            raise web.HTTPForbidden(text="Unexpected Alice skill")
        if (
            utterance.type == "SimpleUtterance"
            and utterance.original_utterance == "ping"
            and not utterance.command
        ):
            return _reply_response(AliceReply("pong", end_session=True))
        if session is None or envelope.version is None:
            raise web.HTTPBadRequest(text="Missing Alice session or version")

        request = _alice_request(utterance, session, envelope.state)
        reply = _builtin_reply(utterance, request)
        if reply is None:
            reply = await _call_handler(handler, request, reply_timeout)
        return _reply_response(reply)

    app = web.Application(client_max_size=64 * 1024)
    app.router.add_post(path, webhook)
    return app
