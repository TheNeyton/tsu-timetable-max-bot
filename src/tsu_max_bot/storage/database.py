from dataclasses import asdict

from alembic import command
from alembic.config import Config
from sqlalchemy import JSON, BigInteger, Column, MetaData, String, Table, Text, delete, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from tsu_max_bot.storage.dto import RegisteredUser

metadata = MetaData()
registered_users = Table(
    "registered_users",
    metadata,
    Column("max_user_id", BigInteger, primary_key=True, autoincrement=False),
    Column("faculty_id", String(255), nullable=False),
    Column("faculty_name", Text, nullable=False),
    Column("group_id", String(255), nullable=False),
    Column("group_name", Text, nullable=False),
    mysql_charset="utf8mb4",
    mysql_engine="InnoDB",
)
schedule_contexts = Table(
    "schedule_contexts",
    metadata,
    Column("user_id", BigInteger, primary_key=True, autoincrement=False),
    Column("chat_id", BigInteger, primary_key=True, autoincrement=False),
    Column("context", JSON, nullable=False),
    mysql_charset="utf8mb4",
    mysql_engine="InnoDB",
)


def _upgrade(connection: Connection) -> None:
    config = Config()
    config.set_main_option("script_location", "tsu_max_bot.storage:migrations")
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


class Database:
    def __init__(self, database_url: str | URL) -> None:
        url = make_url(database_url)
        if url.get_backend_name() == "mysql" and "charset" not in url.query:
            url = url.update_query_dict({"charset": "utf8mb4"})
        self._engine = create_async_engine(url, pool_pre_ping=True, hide_parameters=True)

    async def migrate(self) -> None:
        async with self._engine.begin() as connection:
            if connection.dialect.name == "sqlite":
                # Explicitly include SQLite DDL and the Alembic version in one transaction.
                await connection.exec_driver_sql("BEGIN IMMEDIATE")
            await connection.run_sync(_upgrade)

    async def get_user(self, max_user_id: int) -> RegisteredUser | None:
        query = select(registered_users).where(registered_users.c.max_user_id == max_user_id)
        async with self._engine.connect() as connection:
            result = await connection.execute(query)
            row = result.mappings().one_or_none()
        return RegisteredUser(**row) if row is not None else None

    async def save_user(self, user: RegisteredUser) -> None:
        fields = asdict(user)
        max_user_id = fields.pop("max_user_id")
        if self._engine.dialect.name == "sqlite":
            insert = sqlite_insert(registered_users).values(max_user_id=max_user_id, **fields)
            query = insert.on_conflict_do_update(
                index_elements=[registered_users.c.max_user_id], set_=fields
            )
        else:
            insert = mysql_insert(registered_users).values(max_user_id=max_user_id, **fields)
            query = insert.on_duplicate_key_update(**fields)

        async with self._engine.begin() as connection:
            await connection.execute(query)
            await connection.execute(
                delete(schedule_contexts).where(schedule_contexts.c.user_id == max_user_id)
            )

    async def get_schedule_context(self, chat_id: int, user_id: int) -> dict[str, object] | None:
        query = select(schedule_contexts.c.context).where(
            schedule_contexts.c.chat_id == chat_id, schedule_contexts.c.user_id == user_id
        )
        async with self._engine.connect() as connection:
            return (await connection.execute(query)).scalar_one_or_none()

    async def save_schedule_context(
        self, chat_id: int, user_id: int, context: dict[str, object]
    ) -> None:
        fields = {"chat_id": chat_id, "user_id": user_id, "context": context}
        if self._engine.dialect.name == "sqlite":
            query = (
                sqlite_insert(schedule_contexts)
                .values(**fields)
                .on_conflict_do_update(
                    index_elements=[schedule_contexts.c.user_id, schedule_contexts.c.chat_id],
                    set_={"context": context},
                )
            )
        else:
            query = (
                mysql_insert(schedule_contexts)
                .values(**fields)
                .on_duplicate_key_update(context=context)
            )
        async with self._engine.begin() as connection:
            await connection.execute(query)

    async def close(self) -> None:
        await self._engine.dispose()
