"""playoff match groups and final candidate

Revision ID: 0007_playoff_groups_final
Revises: 0006_site_content_chat_set
Create Date: 2026-02-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_playoff_groups_final"
down_revision = "0006_site_content_chat_set"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "playoff_stages",
        sa.Column("final_candidate_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("playoff_matches", sa.Column("group_number", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("playoff_matches", sa.Column("game_number", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_playoff_matches_group_number", "playoff_matches", ["group_number"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_playoff_matches_group_number", table_name="playoff_matches")
    op.drop_column("playoff_matches", "game_number")
    op.drop_column("playoff_matches", "group_number")
    op.drop_column("playoff_stages", "final_candidate_user_id")
