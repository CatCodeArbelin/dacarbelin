"""manual draw metadata

Revision ID: 0009_manual_draw_mode
Revises: 0008_group_match_schedule
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_manual_draw_mode"
down_revision = "0008_group_match_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tournament_groups", sa.Column("draw_mode", sa.String(length=20), nullable=False, server_default="auto"))


def downgrade() -> None:
    op.drop_column("tournament_groups", "draw_mode")
