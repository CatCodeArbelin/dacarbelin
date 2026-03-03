"""add eighth places counter for playoff participants

Revision ID: 0017_add_playoff_eighth_places
Revises: 0016_stage_keys_to_stage2
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0017_add_playoff_eighth_places"
down_revision = "0016_stage_keys_to_stage2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "playoff_participants",
        sa.Column("eighth_places", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("playoff_participants", "eighth_places")
