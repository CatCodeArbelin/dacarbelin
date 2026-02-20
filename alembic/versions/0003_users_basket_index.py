"""users basket index

Revision ID: 0003_users_basket_index
Revises: 0002_tournament_groups
Create Date: 2026-02-20
"""

from alembic import op


revision = "0003_users_basket_index"
down_revision = "0002_tournament_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем индекс для ускорения агрегации/фильтрации по корзине.
    op.create_index("ix_users_basket", "users", ["basket"], unique=False)


def downgrade() -> None:
    # Удаляем индекс корзины пользователей.
    op.drop_index("ix_users_basket", table_name="users")
