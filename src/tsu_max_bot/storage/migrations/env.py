from alembic import context

from tsu_max_bot.storage.database import metadata

context.configure(
    connection=context.config.attributes["connection"],
    target_metadata=metadata,
)
with context.begin_transaction():
    context.run_migrations()
