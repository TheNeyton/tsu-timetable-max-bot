"""Remember the last schedule query per MAX conversation."""

import sqlalchemy as sa
from alembic import op

revision = "0002_schedule_context"
down_revision = "0001_registered_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_contexts",
        sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("chat_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("context", sa.JSON(), nullable=False),
        if_not_exists=True,
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("schedule_contexts")
