"""Create the table for completed MAX user registrations."""

import sqlalchemy as sa
from alembic import op

revision = "0001_registered_users"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registered_users",
        sa.Column("max_user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("faculty_id", sa.String(255), nullable=False),
        sa.Column("faculty_name", sa.Text(), nullable=False),
        sa.Column("group_id", sa.String(255), nullable=False),
        sa.Column("group_name", sa.Text(), nullable=False),
        # MySQL commits DDL before Alembic records the revision, so allow a retry.
        if_not_exists=True,
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("registered_users")
