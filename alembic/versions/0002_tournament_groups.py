"""tournament groups

Revision ID: 0002_tournament_groups
Revises: 0001_initial
Create Date: 2026-02-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_tournament_groups"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаем таблицу групп турнира.
    op.create_table(
        "tournament_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("lobby_password", sa.String(length=4), nullable=False),
        sa.Column("current_game", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_tournament_groups_stage", "tournament_groups", ["stage"], unique=False)
    op.create_index("ix_tournament_groups_name", "tournament_groups", ["name"], unique=False)

    # Создаем таблицу участников групп.
    op.create_table(
        "group_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("tournament_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seat", sa.Integer(), nullable=False),
        sa.Column("total_points", sa.Integer(), nullable=False),
        sa.Column("first_places", sa.Integer(), nullable=False),
        sa.Column("top4_finishes", sa.Integer(), nullable=False),
        sa.Column("eighth_places", sa.Integer(), nullable=False),
        sa.Column("last_game_place", sa.Integer(), nullable=False),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_user"),
    )
    op.create_index("ix_group_members_group_id", "group_members", ["group_id"], unique=False)
    op.create_index("ix_group_members_user_id", "group_members", ["user_id"], unique=False)

    # Создаем таблицу результатов игр в группах.
    op.create_table(
        "group_game_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("tournament_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("game_number", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("place", sa.Integer(), nullable=False),
        sa.Column("points_awarded", sa.Integer(), nullable=False),
        sa.UniqueConstraint("group_id", "game_number", "place", name="uq_group_game_place"),
    )
    op.create_index("ix_group_game_results_group_id", "group_game_results", ["group_id"], unique=False)
    op.create_index("ix_group_game_results_game_number", "group_game_results", ["game_number"], unique=False)
    op.create_index("ix_group_game_results_user_id", "group_game_results", ["user_id"], unique=False)


def downgrade() -> None:
    # Удаляем таблицы турнирного движка.
    op.drop_index("ix_group_game_results_user_id", table_name="group_game_results")
    op.drop_index("ix_group_game_results_game_number", table_name="group_game_results")
    op.drop_index("ix_group_game_results_group_id", table_name="group_game_results")
    op.drop_table("group_game_results")
    op.drop_index("ix_group_members_user_id", table_name="group_members")
    op.drop_index("ix_group_members_group_id", table_name="group_members")
    op.drop_table("group_members")
    op.drop_index("ix_tournament_groups_name", table_name="tournament_groups")
    op.drop_index("ix_tournament_groups_stage", table_name="tournament_groups")
    op.drop_table("tournament_groups")
