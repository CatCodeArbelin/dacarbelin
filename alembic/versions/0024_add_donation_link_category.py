"""add category to donation links

Revision ID: 0024_add_donation_link_category
Revises: 0023_crypto_wallets_and_donor_amount_integer
Create Date: 2026-03-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0024_add_donation_link_category"
down_revision = "0023_crypto_wallets_and_donor_amount_integer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "donation_links",
        sa.Column("category", sa.String(length=50), nullable=False, server_default="general"),
    )
    op.alter_column("donation_links", "category", server_default=None)


def downgrade() -> None:
    op.drop_column("donation_links", "category")
