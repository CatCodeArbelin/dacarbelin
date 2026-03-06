"""add crypto wallets and make donor amount numeric

Revision ID: 0023_crypto_wallets_and_donor_amount_integer
Revises: 0022_add_direct_invite_group_number
Create Date: 2026-03-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0023_crypto_wallets_and_donor_amount_integer"
down_revision = "0022_add_direct_invite_group_number"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crypto_wallets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wallet_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("requisites", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.add_column("donors", sa.Column("amount_int", sa.Integer(), nullable=False, server_default="0"))
    op.execute(
        """
        UPDATE donors
        SET amount_int = CAST(
            CASE
                WHEN amount IS NULL OR TRIM(amount) = '' THEN '0'
                ELSE REPLACE(REPLACE(REPLACE(REPLACE(amount, '$', ''), '€', ''), ',', ''), ' ', '')
            END
            AS INTEGER
        )
        """
    )
    op.drop_column("donors", "amount")
    op.alter_column("donors", "amount_int", new_column_name="amount", server_default=None)


def downgrade() -> None:
    op.add_column("donors", sa.Column("amount_text", sa.String(length=120), nullable=False, server_default=""))
    op.execute("UPDATE donors SET amount_text = CAST(amount AS TEXT)")
    op.drop_column("donors", "amount")
    op.alter_column("donors", "amount_text", new_column_name="amount", server_default="")

    op.drop_table("crypto_wallets")
