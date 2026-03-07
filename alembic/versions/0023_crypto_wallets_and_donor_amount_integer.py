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
        -- Legacy parsing policy:
        -- 1) keep only digits and minus sign via regexp_replace
        -- 2) treat empty/non-convertible result as 0 (defensive fallback)
        -- 3) fractional separators are removed with other non-digits, so
        --    legacy fractional values are effectively truncated to a whole-number string
        --    before CAST (e.g. "12.34" -> "1234")
        UPDATE donors
        SET amount_int = CASE
            WHEN src.sanitized_amount = '' THEN 0
            WHEN src.sanitized_amount ~ '^-?[0-9]+$' THEN CAST(src.sanitized_amount AS INTEGER)
            ELSE 0
        END
        FROM (
            SELECT
                id,
                regexp_replace(COALESCE(amount, ''), '[^0-9-]', '', 'g') AS sanitized_amount
            FROM donors
        ) AS src
        WHERE donors.id = src.id
        """
    )
    op.drop_column("donors", "amount")
    op.alter_column("donors", "amount_int", new_column_name="amount", server_default=None)


def downgrade() -> None:
    op.add_column("donors", sa.Column("amount_text", sa.String(length=120), nullable=False, server_default=""))
    # Formatting/currency symbols from the original string amount are already lost in upgrade().
    op.execute("UPDATE donors SET amount_text = CAST(amount AS TEXT)")
    op.drop_column("donors", "amount")
    op.alter_column("donors", "amount_text", new_column_name="amount", server_default="")

    op.drop_table("crypto_wallets")
