"""add chat nick color and judge login token setting

Revision ID: 0015_chat_color_and_judge_token
Revises: 0014_add_top8_finishes_counters
Create Date: 2026-02-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0015_chat_color_and_judge_token"
down_revision = "0014_add_top8_finishes_counters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("nick_color", sa.String(length=7), nullable=False, server_default="#00d4ff"))


def downgrade() -> None:
    op.drop_column("chat_messages", "nick_color")
