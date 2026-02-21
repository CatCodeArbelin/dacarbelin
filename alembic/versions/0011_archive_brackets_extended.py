"""archive bracket fields

Revision ID: 0011_archive_brackets
Revises: 0010_playoff_stage_codes
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_archive_brackets"
down_revision = "0010_playoff_stage_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("archive_entries", sa.Column("champion_name", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("archive_entries", sa.Column("bracket_payload", sa.Text(), nullable=False, server_default=""))
    op.add_column("archive_entries", sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("archive_entries", "is_published")
    op.drop_column("archive_entries", "bracket_payload")
    op.drop_column("archive_entries", "champion_name")
