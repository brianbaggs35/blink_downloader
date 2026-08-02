"""tier2 linked to tier1

Revision ID: 5030946cd741
Revises: d81263dff5a9
Create Date: 2026-08-02 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5030946cd741"
down_revision: str | None = "d81263dff5a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_settings",
        sa.Column(
            "tier2_linked_to_tier1",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_settings", "tier2_linked_to_tier1")
