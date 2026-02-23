"""expand playoff stage code length

Revision ID: 0013_expand_stage_code_len
Revises: 0012_direct_invite_stage2
Create Date: 2026-02-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_expand_stage_code_len"
down_revision = "0012_direct_invite_stage2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "playoff_stages",
        "stage_code",
        existing_type=sa.String(length=20),
        type_=sa.String(length=50),
        existing_nullable=False,
        existing_server_default="playoff",
    )


def downgrade() -> None:
    op.alter_column(
        "playoff_stages",
        "stage_code",
        existing_type=sa.String(length=50),
        type_=sa.String(length=20),
        existing_nullable=False,
        existing_server_default="playoff",
    )
