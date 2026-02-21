"""playoff stage codes and manual overrides

Revision ID: 0010_playoff_stage_codes
Revises: 0009_manual_draw_mode
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_playoff_stage_codes"
down_revision = "0009_manual_draw_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("playoff_stages", sa.Column("stage_code", sa.String(length=20), nullable=False, server_default="playoff"))
    op.add_column(
        "playoff_matches",
        sa.Column("manual_winner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("playoff_matches", sa.Column("manual_override_note", sa.String(length=255), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("playoff_matches", "manual_override_note")
    op.drop_column("playoff_matches", "manual_winner_user_id")
    op.drop_column("playoff_stages", "stage_code")
