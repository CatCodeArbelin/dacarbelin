"""migrate legacy playoff stage keys to stage_2

Revision ID: 0016_stage_keys_to_stage2
Revises: 0015_chat_colors_sender_token
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_stage_keys_to_stage2"
down_revision = "0015_chat_colors_sender_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                legacy_stage_id INTEGER;
                stage_2_id INTEGER;
            BEGIN
                SELECT id INTO legacy_stage_id FROM playoff_stages WHERE key='stage_1_8' LIMIT 1;
                SELECT id INTO stage_2_id FROM playoff_stages WHERE key='stage_2' LIMIT 1;

                IF legacy_stage_id IS NOT NULL AND stage_2_id IS NULL THEN
                    UPDATE playoff_stages
                    SET key='stage_2',
                        title='Stage 2',
                        stage_size=32,
                        stage_order=0,
                        stage_code='stage_2'
                    WHERE id=legacy_stage_id;
                ELSIF legacy_stage_id IS NOT NULL AND stage_2_id IS NOT NULL THEN
                    DELETE FROM playoff_stages
                    WHERE id=legacy_stage_id;
                END IF;
            END
            $$;
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE users
            SET direct_invite_stage='stage_2'
            WHERE direct_invite_stage='stage_1_8'
            """
        )
    )


def downgrade() -> None:
    op.execute(
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
    op.execute(
        sa.text(
            """
            UPDATE users
            SET direct_invite_stage='stage_1_8'
            WHERE direct_invite_stage='stage_2'
            """
        )
    )
