"""add top8 finishes counters

Revision ID: 0014_add_top8_finishes_counters
Revises: 0013_expand_stage_code_len
Create Date: 2026-02-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0014_add_top8_finishes_counters"
down_revision = "0013_expand_stage_code_len"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("group_members", sa.Column("top8_finishes", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("playoff_participants", sa.Column("top8_finishes", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("playoff_participants", "top8_finishes")
    op.drop_column("group_members", "top8_finishes")
