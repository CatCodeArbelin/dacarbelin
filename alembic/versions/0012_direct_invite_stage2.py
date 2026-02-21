"""add direct invite stage flag for users

Revision ID: 0012_direct_invite_stage2
Revises: 0011_archive_brackets
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_direct_invite_stage2"
down_revision = "0011_archive_brackets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("direct_invite_stage", sa.String(length=50), nullable=True))
    op.create_index(op.f("ix_users_direct_invite_stage"), "users", ["direct_invite_stage"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_direct_invite_stage"), table_name="users")
    op.drop_column("users", "direct_invite_stage")
