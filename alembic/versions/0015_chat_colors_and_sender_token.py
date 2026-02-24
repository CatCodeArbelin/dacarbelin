"""add chat color and sender token

Revision ID: 0015_chat_colors_and_sender_token
Revises: 0014_add_top8_finishes_counters
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_chat_colors_and_sender_token"
down_revision = "0014_add_top8_finishes_counters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("nick_color", sa.String(length=7), nullable=False, server_default="#00d4ff"))
    op.add_column("chat_messages", sa.Column("sender_token", sa.String(length=160), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("chat_messages", "sender_token")
    op.drop_column("chat_messages", "nick_color")
