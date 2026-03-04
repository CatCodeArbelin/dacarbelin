"""add emergency operation logs

Revision ID: 0021_add_emergency_operation_logs
Revises: 0020_localize_content_entities
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_add_emergency_operation_logs"
down_revision = "0020_localize_content_entities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "emergency_operation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_name", sa.String(length=120), nullable=False, server_default="admin"),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("target_stage_id", sa.Integer(), sa.ForeignKey("playoff_stages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_emergency_operation_logs_action_type", "emergency_operation_logs", ["action_type"])
    op.create_index("ix_emergency_operation_logs_target_stage_id", "emergency_operation_logs", ["target_stage_id"])
    op.create_index("ix_emergency_operation_logs_created_at", "emergency_operation_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_emergency_operation_logs_created_at", table_name="emergency_operation_logs")
    op.drop_index("ix_emergency_operation_logs_target_stage_id", table_name="emergency_operation_logs")
    op.drop_index("ix_emergency_operation_logs_action_type", table_name="emergency_operation_logs")
    op.drop_table("emergency_operation_logs")
