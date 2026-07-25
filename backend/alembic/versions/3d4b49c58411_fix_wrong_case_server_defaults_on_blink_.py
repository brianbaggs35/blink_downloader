"""fix wrong-case server defaults on blink enum columns

Revision ID: 3d4b49c58411
Revises: 563b2434dc8e
Create Date: 2026-07-25 22:47:54.213046
"""
from collections.abc import Sequence

from alembic import op


revision: str = '3d4b49c58411'
down_revision: str | None = '563b2434dc8e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # str_enum() columns store the Python member NAME (e.g. 'ACTIVE'), not
    # .value (e.g. 'active') - these two server_defaults were written with
    # .value by mistake. Never hit through the ORM (its Python-side default=
    # always wins), only by a raw INSERT that omits the column - alembic's
    # autogenerate doesn't diff server_default by default, so this is
    # hand-written rather than generated.
    op.alter_column("blink_accounts", "status", server_default="ACTIVE")
    op.alter_column("clips", "storage_backend", server_default="LOCAL")


def downgrade() -> None:
    op.alter_column("blink_accounts", "status", server_default="active")
    op.alter_column("clips", "storage_backend", server_default="local")
