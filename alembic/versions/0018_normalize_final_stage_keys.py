"""normalize legacy final playoff stage keys

Revision ID: 0018_normalize_final_stage_keys
Revises: 0017_add_playoff_eighth_places
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_normalize_final_stage_keys"
down_revision = "0017_add_playoff_eighth_places"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE playoff_stages
            SET key='stage_final',
                stage_code='stage_final'
            WHERE key IN ('final', 'stage_4')
            """
        )
    )


def downgrade() -> None:
    # Точное восстановление legacy-ключей неидемпотентно без отдельного маркера,
    # поэтому миграция откатывается как no-op.
    pass
