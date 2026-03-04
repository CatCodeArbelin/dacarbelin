"""localize site content entities

Revision ID: 0020_localize_content_entities
Revises: 0019_create_tournament_archives
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_localize_content_entities"
down_revision = "0019_create_tournament_archives"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("donation_links", sa.Column("title_ru", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("donation_links", sa.Column("title_en", sa.String(length=120), nullable=False, server_default=""))

    op.add_column("donation_methods", sa.Column("label_ru", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("donation_methods", sa.Column("label_en", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("donation_methods", sa.Column("details_ru", sa.Text(), nullable=False, server_default=""))
    op.add_column("donation_methods", sa.Column("details_en", sa.Text(), nullable=False, server_default=""))

    op.add_column("prize_pool_entries", sa.Column("place_label_ru", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("prize_pool_entries", sa.Column("place_label_en", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("prize_pool_entries", sa.Column("reward_ru", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("prize_pool_entries", sa.Column("reward_en", sa.String(length=255), nullable=False, server_default=""))

    op.add_column("donors", sa.Column("message_ru", sa.Text(), nullable=False, server_default=""))
    op.add_column("donors", sa.Column("message_en", sa.Text(), nullable=False, server_default=""))

    op.add_column("rules_content", sa.Column("body_ru", sa.Text(), nullable=False, server_default=""))
    op.add_column("rules_content", sa.Column("body_en", sa.Text(), nullable=False, server_default=""))

    op.execute("UPDATE donation_links SET title_ru = title")
    op.execute("UPDATE donation_methods SET label_ru = label, details_ru = details")
    op.execute("UPDATE prize_pool_entries SET place_label_ru = place_label, reward_ru = reward")
    op.execute("UPDATE donors SET message_ru = message")
    op.execute("UPDATE rules_content SET body_ru = body")

    op.drop_column("donation_links", "title")
    op.drop_column("donation_methods", "label")
    op.drop_column("donation_methods", "details")
    op.drop_column("prize_pool_entries", "place_label")
    op.drop_column("prize_pool_entries", "reward")
    op.drop_column("donors", "message")
    op.drop_column("rules_content", "body")


def downgrade() -> None:
    op.add_column("rules_content", sa.Column("body", sa.Text(), nullable=False, server_default=""))
    op.add_column("donors", sa.Column("message", sa.Text(), nullable=False, server_default=""))
    op.add_column("prize_pool_entries", sa.Column("reward", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("prize_pool_entries", sa.Column("place_label", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("donation_methods", sa.Column("details", sa.Text(), nullable=False, server_default=""))
    op.add_column("donation_methods", sa.Column("label", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("donation_links", sa.Column("title", sa.String(length=120), nullable=False, server_default=""))

    op.execute("UPDATE donation_links SET title = title_ru")
    op.execute("UPDATE donation_methods SET label = label_ru, details = details_ru")
    op.execute("UPDATE prize_pool_entries SET place_label = place_label_ru, reward = reward_ru")
    op.execute("UPDATE donors SET message = message_ru")
    op.execute("UPDATE rules_content SET body = body_ru")

    op.drop_column("donation_links", "title_en")
    op.drop_column("donation_links", "title_ru")
    op.drop_column("donation_methods", "details_en")
    op.drop_column("donation_methods", "details_ru")
    op.drop_column("donation_methods", "label_en")
    op.drop_column("donation_methods", "label_ru")
    op.drop_column("prize_pool_entries", "reward_en")
    op.drop_column("prize_pool_entries", "reward_ru")
    op.drop_column("prize_pool_entries", "place_label_en")
    op.drop_column("prize_pool_entries", "place_label_ru")
    op.drop_column("donors", "message_en")
    op.drop_column("donors", "message_ru")
    op.drop_column("rules_content", "body_en")
    op.drop_column("rules_content", "body_ru")
