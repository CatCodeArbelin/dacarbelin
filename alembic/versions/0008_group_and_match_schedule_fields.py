"""group and playoff match schedule fields

Revision ID: 0008_group_and_match_schedule_fields
Revises: 0007_playoff_match_groups_and_final_candidate
Create Date: 2026-02-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_group_and_match_schedule_fields"
down_revision = "0007_playoff_match_groups_and_final_candidate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tournament_groups", sa.Column("scheduled_at", sa.DateTime(), nullable=True))
    op.add_column("tournament_groups", sa.Column("schedule_text", sa.String(length=120), nullable=False, server_default="TBD"))
    op.add_column("playoff_matches", sa.Column("scheduled_at", sa.DateTime(), nullable=True))
    op.add_column("playoff_matches", sa.Column("schedule_text", sa.String(length=120), nullable=False, server_default="TBD"))


def downgrade() -> None:
    op.drop_column("playoff_matches", "schedule_text")
    op.drop_column("playoff_matches", "scheduled_at")
    op.drop_column("tournament_groups", "schedule_text")
    op.drop_column("tournament_groups", "scheduled_at")
