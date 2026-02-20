"""group manual tie breaks

Revision ID: 0004_group_manual_tie_breaks
Revises: 0003_users_basket_index
Create Date: 2026-02-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_group_manual_tie_breaks"
down_revision = "0003_users_basket_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем таблицу для фиксации ручных тай-брейков в спорных кейсах.
    op.create_table(
        "group_manual_tie_breaks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("tournament_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_manual_tie_break_user"),
        sa.UniqueConstraint("group_id", "priority", name="uq_group_manual_tie_break_priority"),
    )
    op.create_index("ix_group_manual_tie_breaks_group_id", "group_manual_tie_breaks", ["group_id"], unique=False)
    op.create_index("ix_group_manual_tie_breaks_user_id", "group_manual_tie_breaks", ["user_id"], unique=False)


def downgrade() -> None:
    # Удаляем таблицу ручных тай-брейков.
    op.drop_index("ix_group_manual_tie_breaks_user_id", table_name="group_manual_tie_breaks")
    op.drop_index("ix_group_manual_tie_breaks_group_id", table_name="group_manual_tie_breaks")
    op.drop_table("group_manual_tie_breaks")
