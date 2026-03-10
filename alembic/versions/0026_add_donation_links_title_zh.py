"""add donation_links.title_zh

Revision ID: 0026_add_donation_links_title_zh
Revises: 0025_add_rules_content_body_zh
Create Date: 2026-03-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0026_add_donation_links_title_zh"
down_revision = "0025_add_rules_content_body_zh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("donation_links", sa.Column("title_zh", sa.String(length=120), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("donation_links", "title_zh")
