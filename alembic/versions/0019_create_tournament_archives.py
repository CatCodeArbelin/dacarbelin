"""create tournament archives table

Revision ID: 0019_create_tournament_archives
Revises: 0018_normalize_final_stage_keys
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_create_tournament_archives"
down_revision = "0018_normalize_final_stage_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tournament_archives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("season", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("winner_user_id", sa.Integer(), nullable=True),
        sa.Column("winner_nickname", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("bracket_payload_json", sa.Text(), nullable=False, server_default=""),
        sa.Column("group_payload_json", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_tournament_version", sa.String(length=64), nullable=False, server_default="legacy"),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["winner_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_tournament_archives_created_at", "tournament_archives", ["created_at"])
    op.create_index("ix_tournament_archives_winner_user_id", "tournament_archives", ["winner_user_id"])
    op.create_index("ix_tournament_archives_is_public", "tournament_archives", ["is_public"])


def downgrade() -> None:
    op.drop_index("ix_tournament_archives_is_public", table_name="tournament_archives")
    op.drop_index("ix_tournament_archives_winner_user_id", table_name="tournament_archives")
    op.drop_index("ix_tournament_archives_created_at", table_name="tournament_archives")
    op.drop_table("tournament_archives")
