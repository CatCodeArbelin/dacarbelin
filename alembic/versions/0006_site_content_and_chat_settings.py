"""site content and chat settings

Revision ID: 0006_site_content_chat_set
Revises: 0005_playoff_stages_and_controls
Create Date: 2026-02-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_site_content_chat_set"
down_revision = "0005_playoff_stages_and_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "donation_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "donation_methods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("method_type", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "prize_pool_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("place_label", sa.String(length=120), nullable=False),
        sa.Column("reward", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "donors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "rules_content",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "archive_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("season", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("link_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "chat_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("max_length", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_table("chat_settings")
    op.drop_table("archive_entries")
    op.drop_table("rules_content")
    op.drop_table("donors")
    op.drop_table("prize_pool_entries")
    op.drop_table("donation_methods")
    op.drop_table("donation_links")
