import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from secrets import token_hex
from time import monotonic

from maxapi.context import SimpleEventIsolation
from maxapi.enums import ChatType
from maxapi.types import BotStarted, MessageCallback, MessageCreated
from maxapi.types.attachments.buttons import CallbackButton
from maxapi.types.attachments.buttons.attachment_button import AttachmentButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from sqlalchemy.exc import SQLAlchemyError

from tsu_max_bot.max_bot.handlers import echo_message
from tsu_max_bot.storage import Database, RegisteredUser
from tsu_max_bot.timetable import Faculty, Group, TimetableClient, TimetableError

logger = logging.getLogger(__name__)

PAGE_SIZE = 8
SESSION_SECONDS = 20 * 60
CALLBACK_PREFIX = "registration:"
RESTART = "Этот выбор устарел. Отправьте /start, чтобы начать заново."
CATALOG_ERROR = "Каталог ТГУ временно недоступен. Попробуйте ещё раз."
DATABASE_ERROR = "Хранилище временно недоступно. Попробуйте ещё раз."
NO_FACULTIES = "Список факультетов ТГУ пуст. Повторите команду /start позже."


@dataclass(frozen=True)
class _ChoicePage:
    options: Sequence[Faculty | Group]
    faculty: Faculty | None = None
    index: int = 0
    token: str = field(default_factory=lambda: token_hex(8))
    expires_at: float = field(default_factory=lambda: monotonic() + SESSION_SECONDS)

    @property
    def prefix(self) -> str:
        return f"{CALLBACK_PREFIX}{self.token}:"

    @property
    def has_next(self) -> bool:
        return (self.index + 1) * PAGE_SIZE < len(self.options)

    def choices(self) -> dict[str, Faculty | Group]:
        start = self.index * PAGE_SIZE
        return {
            str(number): option
            for number, option in enumerate(self.options[start : start + PAGE_SIZE], start + 1)
        }

    def render(self) -> tuple[str, list[AttachmentButton]]:
        choices = self.choices()
        if self.faculty is None:
            lines = ["Выберите Ваш факультет:"]
        else:
            lines = [f"{self.faculty.name}\nВыберите Вашу группу:"]
        lines.extend(f"{number}. {option.name}" for number, option in choices.items())

        def button(label: str, action: str) -> CallbackButton:
            return CallbackButton(text=label, payload=self.prefix + action)

        keyboard = InlineKeyboardBuilder()
        keyboard.add(*(button(number, number) for number in choices)).adjust(4)
        navigation = []
        if self.index:
            navigation.append(button("Назад", "previous"))
        if self.has_next:
            navigation.append(button("Далее", "next"))
        if navigation:
            keyboard.row(*navigation)
        if self.faculty is not None:
            keyboard.row(button("К факультетам", "faculties"))
        return "\n".join(lines), [keyboard.as_markup()]


def _profile_text(user: RegisteredUser) -> str:
    return f"Факультет: {user.faculty_name}\nГруппа: {user.group_name}"


class Registration:
    def __init__(self, timetable: TimetableClient, database: Database) -> None:
        self._timetable = timetable
        self._database = database
        self._pages: dict[int, _ChoicePage] = {}
        self._isolation = SimpleEventIsolation()

    async def bot_started(self, event: BotStarted) -> None:
        if not event.user.is_bot:
            await self._start(event.user.user_id, event.send)

    async def message_created(self, event: MessageCreated) -> None:
        message = event.message
        sender = message.sender
        if sender is None or sender.is_bot or message.body is None or not message.body.text:
            return
        command = message.body.text.split(maxsplit=1)
        if message.recipient.chat_type == ChatType.DIALOG and command and command[0] == "/start":
            await self._start(sender.user_id, message.answer)
        else:
            await echo_message(event)

    async def _start(self, user_id: int, reply: Callable[..., Awaitable[object]]) -> None:
        async with self._isolation.lock((None, user_id)):
            now = monotonic()
            self._pages = {
                owner: page for owner, page in self._pages.items() if page.expires_at > now
            }
            try:
                user = await self._database.get_user(user_id)
            except SQLAlchemyError:
                logger.exception("Не удалось загрузить профиль пользователя MAX.")
                await reply(f"{DATABASE_ERROR}\nПовторите команду /start.")
                return
            if user is not None:
                self._pages.pop(user_id, None)
                await reply(f"Вы уже зарегистрированы.\n{_profile_text(user)}")
                return
            try:
                faculties = await self._timetable.get_faculties()
            except TimetableError:
                logger.exception("Не удалось получить список факультетов ТГУ.")
                await reply(f"{CATALOG_ERROR}\nПовторите команду /start.")
                return
            if not faculties:
                await reply(NO_FACULTIES)
                return

            page = _ChoicePage(faculties)
            text, attachments = page.render()
            if await reply(text, attachments=attachments) is not None:
                self._pages[user_id] = page

    async def message_callback(self, event: MessageCallback) -> None:
        payload = event.callback.payload
        user = event.callback.user
        if not payload or not payload.startswith(CALLBACK_PREFIX) or user.is_bot:
            return
        message = event.message
        if (
            message is None
            or message.body is None
            or message.recipient.chat_type != ChatType.DIALOG
        ):
            await event.ack(RESTART)
            return

        user_id = user.user_id
        async with self._isolation.lock((None, user_id)):
            page = self._pages.get(user_id)
            if page is not None and page.expires_at <= monotonic():
                self._pages.pop(user_id)
                page = None
            if page is None or not payload.startswith(page.prefix):
                await event.ack(RESTART)
                return

            action = payload.removeprefix(page.prefix)
            option = page.choices().get(action)
            try:
                if isinstance(option, Faculty):
                    groups = await self._timetable.get_groups(option.id)
                    if not groups:
                        await event.ack("У этого факультета пока нет групп. Выберите другой.")
                        return
                    next_page = _ChoicePage(groups, faculty=option)
                elif isinstance(option, Group) and page.faculty is not None:
                    await self._save(event, user_id, page.faculty, option)
                    return
                elif action == "previous" and page.index > 0:
                    next_page = _ChoicePage(page.options, page.faculty, page.index - 1)
                elif action == "next" and page.has_next:
                    next_page = _ChoicePage(page.options, page.faculty, page.index + 1)
                elif action == "faculties" and page.faculty is not None:
                    faculties = await self._timetable.get_faculties()
                    if not faculties:
                        await event.ack(NO_FACULTIES)
                        return
                    next_page = _ChoicePage(faculties)
                else:
                    await event.ack(RESTART)
                    return
            except TimetableError:
                logger.exception("Не удалось получить данные каталога ТГУ.")
                await event.ack(CATALOG_ERROR)
                return

            text, attachments = next_page.render()
            result = await event.edit(text, attachments=attachments)
            if result.success:
                self._pages[user_id] = next_page

    async def _save(
        self, event: MessageCallback, user_id: int, faculty: Faculty, group: Group
    ) -> None:
        user = RegisteredUser(
            max_user_id=user_id,
            faculty_id=faculty.id,
            faculty_name=faculty.name,
            group_id=group.id,
            group_name=group.name,
        )
        try:
            await self._database.save_user(user)
        except SQLAlchemyError:
            logger.exception("Не удалось сохранить профиль пользователя MAX.")
            await event.ack(DATABASE_ERROR)
            return

        self._pages.pop(user_id, None)
        await event.edit(f"Регистрация завершена.\n{_profile_text(user)}", attachments=[])
