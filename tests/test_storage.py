import asyncio
from dataclasses import replace

from tsu_max_bot.storage import Database, RegisteredUser

USER = RegisteredUser(
    max_user_id=4_200_000_001,
    faculty_id="faculty-id",
    faculty_name="Факультет информатики",
    group_id="group-id",
    group_name="12345",
)


def test_registration_survives_database_reopen_and_migration_rerun(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'registration.sqlite3').as_posix()}"

    async def run():
        database = Database(url)
        try:
            await database.migrate()
            assert await database.get_user(USER.max_user_id) is None
            await database.save_user(USER)
        finally:
            await database.close()

        reopened = Database(url)
        try:
            await reopened.migrate()
            assert await reopened.get_user(USER.max_user_id) == USER
        finally:
            await reopened.close()

    asyncio.run(run())


def test_concurrent_registration_retries_keep_one_complete_profile(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'registration.sqlite3').as_posix()}"
    updated = replace(
        USER,
        faculty_id="other-faculty-id",
        faculty_name="Факультет математики",
        group_id="other-group-id",
        group_name="67890",
    )
    other_user = replace(USER, max_user_id=USER.max_user_id + 1)

    async def run():
        database = Database(url)
        try:
            await database.migrate()
            await database.save_user(other_user)
            await asyncio.gather(database.save_user(USER), database.save_user(updated))
            assert await database.get_user(USER.max_user_id) in (USER, updated)
            await database.save_user(updated)
            assert await database.get_user(USER.max_user_id) == updated
            assert await database.get_user(other_user.max_user_id) == other_user
        finally:
            await database.close()

    asyncio.run(run())
