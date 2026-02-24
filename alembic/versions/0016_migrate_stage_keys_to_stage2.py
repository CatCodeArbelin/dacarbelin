"""migrate legacy playoff stage keys to stage_2

Revision ID: 0016_migrate_stage_keys_to_stage2
Revises: 0015_chat_colors_and_sender_token
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_migrate_stage_keys_to_stage2"
down_revision = "0015_chat_colors_and_sender_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    legacy_stage_id = bind.execute(sa.text("SELECT id FROM playoff_stages WHERE key='stage_1_8' LIMIT 1")).scalar()
    stage_2_id = bind.execute(sa.text("SELECT id FROM playoff_stages WHERE key='stage_2' LIMIT 1")).scalar()

    if legacy_stage_id and not stage_2_id:
        bind.execute(
            sa.text(
                """
                UPDATE playoff_stages
                SET key='stage_2',
                    title='Stage 2',
                    stage_size=32,
                    stage_order=0,
                    stage_code='stage_2'
                WHERE id=:stage_id
                """
            ),
            {"stage_id": int(legacy_stage_id)},
        )
    elif legacy_stage_id and stage_2_id:
        bind.execute(
            sa.text(
                """
                DELETE FROM playoff_stages
                WHERE id=:legacy_stage_id
                """
            ),
            {"legacy_stage_id": int(legacy_stage_id)},
        )


    bind.execute(
        sa.text(
            """
            UPDATE users
            SET direct_invite_stage='stage_2'
            WHERE direct_invite_stage='stage_1_8'
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE playoff_stages
            SET key='stage_1_8',
                title='Stage 1/8',
                stage_code='stage_1_8'
            WHERE key='stage_2'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE users
            SET direct_invite_stage='stage_1_8'
            WHERE direct_invite_stage='stage_2'
            """
        )
    )
