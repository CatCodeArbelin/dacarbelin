"""playoff stages and controls

Revision ID: 0005_playoff_stages_and_controls
Revises: 0004_group_manual_tie_breaks
Create Date: 2026-02-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_playoff_stages_and_controls"
down_revision = "0004_group_manual_tie_breaks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tournament_groups", sa.Column("is_started", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "playoff_stages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("stage_size", sa.Integer(), nullable=False),
        sa.Column("stage_order", sa.Integer(), nullable=False),
        sa.Column("scoring_mode", sa.String(length=32), nullable=False, server_default="standard"),
        sa.Column("is_started", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("key", name="uq_playoff_stage_key"),
    )
    op.create_index("ix_playoff_stages_key", "playoff_stages", ["key"], unique=False)
    op.create_index("ix_playoff_stages_stage_order", "playoff_stages", ["stage_order"], unique=False)

    op.create_table(
        "playoff_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stage_id", sa.Integer(), sa.ForeignKey("playoff_stages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("top4_finishes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_place", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("is_eliminated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("stage_id", "user_id", name="uq_playoff_stage_user"),
    )
    op.create_index("ix_playoff_participants_stage_id", "playoff_participants", ["stage_id"], unique=False)
    op.create_index("ix_playoff_participants_user_id", "playoff_participants", ["user_id"], unique=False)

    op.create_table(
        "playoff_matches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stage_id", sa.Integer(), sa.ForeignKey("playoff_stages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match_number", sa.Integer(), nullable=False),
        sa.Column("lobby_password", sa.String(length=4), nullable=False, server_default="0000"),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("winner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("stage_id", "match_number", name="uq_playoff_stage_match_number"),
    )
    op.create_index("ix_playoff_matches_stage_id", "playoff_matches", ["stage_id"], unique=False)
    op.create_index("ix_playoff_matches_match_number", "playoff_matches", ["match_number"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_playoff_matches_match_number", table_name="playoff_matches")
    op.drop_index("ix_playoff_matches_stage_id", table_name="playoff_matches")
    op.drop_table("playoff_matches")

    op.drop_index("ix_playoff_participants_user_id", table_name="playoff_participants")
    op.drop_index("ix_playoff_participants_stage_id", table_name="playoff_participants")
    op.drop_table("playoff_participants")

    op.drop_index("ix_playoff_stages_stage_order", table_name="playoff_stages")
    op.drop_index("ix_playoff_stages_key", table_name="playoff_stages")
    op.drop_table("playoff_stages")

    op.drop_column("tournament_groups", "is_started")
