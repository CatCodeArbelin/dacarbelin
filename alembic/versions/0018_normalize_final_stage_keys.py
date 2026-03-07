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


# Для точного rollback храним снимок только изменяемых строк в отдельной таблице.
# Marker-столбец в `playoff_stages` менять рискованнее (доп. DDL на боевой таблице),
# а отдельная техтаблица позволяет восстановить key/stage_code по stage_id без
# предположений о том, какими были legacy-значения до нормализации.
ROLLBACK_TABLE = "_tmp_0018_playoff_stage_key_backup"


def upgrade() -> None:
    op.create_table(
        ROLLBACK_TABLE,
        sa.Column("stage_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("old_key", sa.String(length=255), nullable=False),
        sa.Column("old_stage_code", sa.String(length=255), nullable=True),
    )

    op.execute(
        sa.text(
            f"""
            INSERT INTO {ROLLBACK_TABLE} (stage_id, old_key, old_stage_code)
            SELECT id, key, stage_code
            FROM playoff_stages
            WHERE key IN ('final', 'stage_4')
            """
        )
    )

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
    op.execute(
        sa.text(
            f"""
            UPDATE playoff_stages AS ps
            SET key = b.old_key,
                stage_code = b.old_stage_code
            FROM {ROLLBACK_TABLE} AS b
            WHERE ps.id = b.stage_id
            """
        )
    )

    op.drop_table(ROLLBACK_TABLE)
