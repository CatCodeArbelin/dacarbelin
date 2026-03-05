"""add direct invite group number

Revision ID: 0022_add_direct_invite_group_number
Revises: 0021_add_emergency_operation_logs
Create Date: 2026-03-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0022_add_direct_invite_group_number"
down_revision = "0021_add_emergency_operation_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("direct_invite_group_number", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_users_direct_invite_group_number"),
        "users",
        ["direct_invite_group_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_users_direct_invite_group_number"), table_name="users")
    op.drop_column("users", "direct_invite_group_number")
