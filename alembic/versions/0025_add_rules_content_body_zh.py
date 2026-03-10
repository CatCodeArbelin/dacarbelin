"""add zh rules content

Revision ID: 0025_add_rules_content_body_zh
Revises: 0024_add_donation_link_category
Create Date: 2026-03-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0025_add_rules_content_body_zh"
down_revision = "0024_add_donation_link_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rules_content", sa.Column("body_zh", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("rules_content", "body_zh")
