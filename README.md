# TSU Timetable MAX Bot

Студенческий проект бота MAX для работы с расписанием Томского государственного университета.

При первом запуске в личном чате бот предлагает выбрать факультет и группу из TSU.InTime.
После выбора группы он сохраняет профиль по идентификатору пользователя MAX. Повторный
`/start` показывает сохранённые факультет и группу. Если выбор прервался, отправьте
`/start` снова. Вне регистрации бот повторяет входящие текстовые сообщения. Файлы,
голосовые сообщения без текста и сообщения других ботов пропускаются. Ответы с расписанием
и интеграция с Yandex Assistant будут добавлены на следующих этапах.

## Запуск

Нужны Python 3.11 или новее и токен бота из [MAX для партнёров](https://business.max.ru/).
Интеграция использует стороннюю Python-библиотеку [maxapi 1.2.4](https://pypi.org/project/maxapi/).

Из корня проекта в PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Укажите токен в `.env`:

```dotenv
MAX_BOT_TOKEN=your_bot_token
```

Запустите бота:

```powershell
.\.venv\Scripts\python.exe -m tsu_max_bot
```

Также доступны команда `tsu-max-bot` после активации окружения и запуск `python main.py`.
В PyCharm выберите то же виртуальное окружение и корень проекта как рабочий каталог.
Для остановки нажмите Ctrl+C.

Бот использует polling, поэтому публичный сервер не нужен. Если у этого же бота уже есть
webhook-подписка, приложение попросит удалить её перед запуском. Автоматически подписки
не меняются. Подробности - в [документации MAX](https://dev.max.ru/docs/chatbots/bots-coding/prepare).

Без токена приложение завершится с подсказкой о `MAX_BOT_TOKEN`. Локальные тесты
не обращаются к MAX.

## База данных

По умолчанию SQLite хранит профили в файле `tsu_max_bot.sqlite3` в рабочем каталоге.
Чтобы указать другой файл, задайте `DATABASE_URL` в `.env`:

```dotenv
DATABASE_URL=sqlite+aiosqlite:///users.sqlite3
```

Для подключения к MySQL подготовьте базу на сервере и укажите параметры подключения:

```dotenv
DATABASE_URL=mysql+aiomysql://bot:password@db.example.org:3306/tsu_max_bot?charset=utf8mb4
```

Специальные символы в логине или пароле нужно URL-кодировать, например `@` как `%40`.
Бот применяет миграции Alembic перед получением событий MAX. Пользователю MySQL нужны
права на применение миграций и чтение и запись профилей в выбранной базе.

## Структура

```text
src/tsu_max_bot/
    __main__.py          запуск и настройка логирования
    config.py            конфигурация из .env и окружения
    max_bot/
        app.py           подключение MAX и polling
        handlers.py      эхо-обработчик
        registration.py  выбор факультета и группы в MAX
    storage/             доступ к базе, DTO профиля и миграции Alembic
    timetable/
        client.py        запросы к API ТГУ и ошибки
        models.py        модели ответов API
tests/
    fixtures/            сокращённые примеры ответов ТГУ
    test_config.py
    test_max_bot.py
    test_registration.py
    test_storage.py
    test_timetable.py
```

Переменные окружения имеют приоритет над `.env`. `MAX_BOT_TOKEN` обязателен;
`LOG_LEVEL` по умолчанию равен `INFO`. `TSU_API_BASE_URL` и `TSU_API_TIMEOUT` задают
адрес API ТГУ и таймаут запроса в секундах для регистрации и клиента расписания.

## Клиент расписания

Источник - [TSU.InTime](https://intime.tsu.ru/), базовый URL API:
`https://intime.tsu.ru/api/web/v1/`. Для запросов расписания токен MAX не нужен.

```python
import asyncio
from datetime import date

import httpx

from tsu_max_bot.timetable import TimetableClient


async def main():
    async with httpx.AsyncClient() as http:
        timetable = TimetableClient(http)
        faculties = await timetable.get_faculties()
        print(faculties[0].name)

        schedule = await timetable.get_group_schedule(
            group_id="a1a4788e-3b8d-11f0-9dca-6cb3110a6d8e",
            date_from=date(2026, 11, 2),
            date_to=date(2026, 11, 7),
        )
        for day in schedule.grid:
            print(day.date, len(day.lessons))


asyncio.run(main())
```

HTTP-клиент создаёт и закрывает вызывающий код. Адрес API и таймаут можно передать
в `TimetableClient(http, base_url=..., timeout=15.0)`. Для значений из `.env` используйте
`Settings.from_env().tsu_api_base_url` и `.tsu_api_timeout` при создании клиента.

| Метод | Данные |
| --- | --- |
| `get_faculties()` | Факультеты |
| `get_groups(faculty_id)` | Группы факультета |
| `get_professors()` | Преподаватели |
| `get_buildings()` | Корпуса |
| `get_audiences(building_id)` | Аудитории корпуса |
| `get_group_schedule(group_id, date_from, date_to)` | Расписание группы |
| `get_professor_schedule(professor_id, date_from, date_to)` | Расписание преподавателя |
| `get_audience_schedule(audience_id, date_from, date_to)` | Расписание аудитории |

Даты передаются как `datetime.date`; начало периода не должно быть позже конца.
Поиск преподавателей по имени нужно делать по полученному списку: отдельного фильтра
в описанном API нет. Кэширование и повторные запросы пока не реализованы.

В расписании сохраняются и занятия (`Lesson`), и пустые окна (`EmptySlot`).
Преподаватель, аудитория и корпус могут отсутствовать; онлайн-занятие может иметь
аудиторию с названием «Онлайн» и `id=None`.

`starts` и `ends` сохраняют исходные секунды API. Сайт интерпретирует их через Unix-время
в часовом поясе `Asia/Tomsk`: например, `6300` соответствует 08:45, `12000` - 10:20.
Это видно в [коде интерфейса ТГУ](https://intime.tsu.ru/assets/index-e61a4f12.js).
Не следует считать эти числа секундами от местной полуночи. Форматирование времени
будет добавлено при реализации ответов с расписанием.

Ошибки клиента наследуются от `TimetableError`:

- `TimetableApiError` - HTTP-ошибка, код доступен в `status_code`;
- `TimetableConnectionError` - таймаут или другая сетевая ошибка;
- `TimetableResponseError` - некорректный JSON или неожиданная структура ответа.
