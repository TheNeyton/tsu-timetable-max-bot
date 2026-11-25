# TSU Timetable MAX Bot

Студенческий проект бота MAX для работы с расписанием Томского государственного университета.

В личном чате MAX команда `/start` открывает выбор факультета и группы из TSU.InTime.
После регистрации `/start` показывает профиль, `/group` открывает выбор группы на Вашем
факультете, а `/faculty` позволяет заново выбрать факультет и группу. Вопросы без явного
названия группы используют Вашу сохранённую группу.

| Запрос | Что покажет бот |
| --- | --- |
| `Какие пары завтра?` | Пары Вашей группы на завтра |
| `Ближайшая пара` или `/next` | Первую предстоящую пару в пределах 14 дней, включая сегодня |
| `Расписание группы 862401 с 26.11.2026 по 28.11.2026` | Пары указанной группы за период |
| `Расписание преподавателя Бабанов на пятницу` | Пары преподавателя на ближайшую пятницу. При совпадении фамилий бот попросит уточнить ФИО |
| `Какие пары 26.11.2026?`, затем `А на следующий день?` | Пары для той же группы на 26 и 27 ноября соответственно |

Время занятий показано по Томску. Для расписания на сегодня можно отправить `/schedule`.
В MAX последний запрос хранится в базе отдельно для каждого пользователя и чата и доступен
после перезапуска. Смена профиля очищает предыдущий контекст этого пользователя.
В групповом чате используйте `/schedule` или `/next`.

В личном чате MAX можно отправить голосовой вопрос. Если MAX передал расшифровку в Bot API,
бот использует её. Иначе он распознаёт короткую запись локально через Vosk или через
настроенный SpeechKit. Ответ в MAX приходит текстом. В навыке Алисы ответ зачитывается вслух.

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

Для локального запуска и демонстрации MAX используется polling. Если у бота есть
webhook-подписка, приложение попросит удалить её перед запуском. Для промышленного
развёртывания MAX предусматривает отдельный приём событий через вебхук. [Документация MAX](https://dev.max.ru/docs-api/methods/GET/updates/)

Для запуска только навыка Алисы оставьте `MAX_BOT_TOKEN` пустым и задайте `ALICE_ENABLED=true`.
При заданном токене и `ALICE_ENABLED=true` оба канала работают в одном процессе.

## Голос и Yandex Cloud

Для навыка Алисы в `.env` задайте `ALICE_ENABLED=true`. По умолчанию приложение слушает
`127.0.0.1:8080` и принимает `POST /alice/webhook`. Адрес, порт и путь задаются переменными
`ALICE_HOST`, `ALICE_PORT` и `ALICE_WEBHOOK_PATH`. `ALICE_SKILL_ID` позволяет проверять, для
какого навыка пришёл запрос.

1. Создайте пользовательский навык в Яндекс Диалогах. В поле «Webhook URL» укажите публичный
   HTTPS-адрес, который проксирует на локальный маршрут приложения. [Настройки навыка](https://yandex.ru/dev/dialogs/alice/doc/ru/publish-settings)
2. В разделе «Хранилище» включите «Использовать хранилище данных в навыке». Алиса хранит
   контекст уточнения в рамках сеанса и может запомнить группу по команде «Моя группа 862401».
   Чтобы выбрать другую, скажите «Сменить группу». [Хранилище навыка](https://yandex.ru/dev/dialogs/alice/doc/ru/session-persistence)
3. На вкладке тестирования произнесите «Какие пары 26 ноября?» и «А на следующий день?».
   Чтобы узнать ближайшую пару, скажите «Ближайшая пара».

Для локального распознавания установите зависимости `python -m pip install -e ".[voice]"`
в окружении бота. Скачайте русскую модель `vosk-model-small-ru-0.22` (45 МБ) из каталога
Vosk и распакуйте архив в `models` из корня проекта. Если модель лежит в другом месте,
задайте `VOICE_MODEL_PATH`. Поддерживаются записи до 30 секунд и 4 МБ. Локальное
распознавание работает без ключа. [Модели Vosk](https://alphacephei.com/vosk/models)

Для распознавания через SpeechKit задайте `SPEECHKIT_API_KEY`. Нужен
API-ключ сервисного аккаунта с ролью `ai.speechkit-stt.user` и областью
`yc.ai.speechkitStt.execute`. Синхронный SpeechKit v1 поддерживает моно Ogg Opus до 30 секунд
и 1 МБ. [Документация SpeechKit](https://aistudio.yandex.ru/ru/docs/speechkit/stt/api/request-api)

Для дополнительного разбора свободных формулировок в MAX задайте `YANDEX_FOLDER_ID` и
`YANDEX_API_KEY`. Клиент Yandex AI Studio Responses API использует `yandexgpt-5-pro` по
умолчанию. Модель можно задать через `YANDEX_MODEL`. Сервисному аккаунту нужны роли
`ai.assistants.editor` и `ai.languageModels.user`, а API-ключу область
`yc.ai.foundationModels.execute`. Модель преобразует вопрос в запрос. Пары бот получает из
актуального расписания TSU.InTime при каждом обращении. [Аутентификация в Yandex AI Studio](https://aistudio.yandex.ru/ru/docs/ai-studio/api-ref/authentication)

Локальные тесты используют имитации внешних сервисов и HTTP-сервер для проверки протокола
Алисы. Запустите их через `python -m pytest` в окружении проекта.

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
права на применение миграций и чтение и запись профилей и контекста в выбранной базе.

## Структура

```text
src/tsu_max_bot/
    __main__.py          запуск и настройка логирования
    config.py            конфигурация из .env и окружения
    alice/               протокол вебхука Яндекс Диалогов
    max_bot/
        app.py           запуск polling MAX и вебхука Алисы
        handlers.py      отправка ответов в MAX
        registration.py  профиль и входящие сообщения MAX
        voice.py         загрузка аудио MAX и распознавание через SpeechKit
        local_voice.py    локальное распознавание аудио MAX через Vosk
    schedule/            разбор вопросов, контекст, поиск и форматирование пар
    storage/             профили, контекст MAX и миграции Alembic
    timetable/
        client.py        запросы к API ТГУ и ошибки
        models.py        модели ответов API
    yandex_assistant.py  разбор нестандартных запросов через Yandex AI Studio
tests/
    fixtures/            сокращённые примеры ответов ТГУ
```

Переменные окружения имеют приоритет над `.env`. `LOG_LEVEL` по умолчанию равен `INFO`.
`TSU_API_BASE_URL` и `TSU_API_TIMEOUT` задают адрес и таймаут запроса к API ТГУ в секундах.

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
Бот ищет преподавателей в каталоге по фамилии или ФИО. Каталог групп для явных запросов
кэшируется на 10 минут.

В расписании сохраняются и занятия (`Lesson`), и пустые окна (`EmptySlot`).
Преподаватель, аудитория и корпус могут отсутствовать; онлайн-занятие может иметь
аудиторию с названием «Онлайн» и `id=None`.

`starts` и `ends` сохраняют исходные секунды API. Сайт интерпретирует их через Unix-время
в часовом поясе `Asia/Tomsk`: например, `6300` соответствует 08:45, `12000` - 10:20.
Это видно в [коде интерфейса ТГУ](https://intime.tsu.ru/assets/index-aae084ce.js).
Бот использует то же преобразование в местное время при форматировании и поиске ближайшей пары.

Ошибки клиента наследуются от `TimetableError`:

- `TimetableApiError` - HTTP-ошибка, код доступен в `status_code`;
- `TimetableConnectionError` - таймаут или другая сетевая ошибка;
- `TimetableResponseError` - некорректный JSON или неожиданная структура ответа.
