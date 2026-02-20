"""initial

Revision ID: 0001_initial
Revises: 
Create Date: 2026-02-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаем таблицу пользователей.
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nickname", sa.String(length=120), nullable=False),
        sa.Column("steam_input", sa.String(length=255), nullable=False),
        sa.Column("steam_id", sa.String(length=32), nullable=False),
        sa.Column("game_nickname", sa.String(length=255), nullable=False),
        sa.Column("current_rank", sa.String(length=120), nullable=False),
        sa.Column("highest_rank", sa.String(length=120), nullable=False),
        sa.Column("telegram", sa.String(length=255), nullable=True),
        sa.Column("discord", sa.String(length=255), nullable=True),
        sa.Column("basket", sa.String(length=50), nullable=False),
        sa.Column("extra_data", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_steam_id", "users", ["steam_id"], unique=True)

    # Создаем таблицу этапов турнира.
    op.create_table(
        "tournament_stages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("title_ru", sa.String(length=255), nullable=False),
        sa.Column("title_en", sa.String(length=255), nullable=False),
        sa.Column("date_text", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_tournament_stages_key", "tournament_stages", ["key"], unique=True)

    # Создаем таблицу настроек.
    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
    )
    op.create_index("ix_site_settings_key", "site_settings", ["key"], unique=True)

    # Создаем таблицу сообщений чата.
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("temp_nick", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"], unique=False)


def downgrade() -> None:
    # Откатываем схему до пустого состояния.
    op.drop_index("ix_chat_messages_created_at", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_site_settings_key", table_name="site_settings")
    op.drop_table("site_settings")
    op.drop_index("ix_tournament_stages_key", table_name="tournament_stages")
    op.drop_table("tournament_stages")
    op.drop_index("ix_users_steam_id", table_name="users")
    op.drop_table("users")
