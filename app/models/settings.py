from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TournamentStage(Base):
    __tablename__ = "tournament_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title_ru: Mapped[str] = mapped_column(String(255), nullable=False)
    title_en: Mapped[str] = mapped_column(String(255), nullable=False)
    date_text: Mapped[str] = mapped_column(String(120), default="TBD")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)


class SiteSetting(Base):
    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")


class DonationLink(Base):
    __tablename__ = "donation_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class DonationMethod(Base):
    __tablename__ = "donation_methods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    method_type: Mapped[str] = mapped_column(String(20), nullable=False)  # card | crypto
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PrizePoolEntry(Base):
    __tablename__ = "prize_pool_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    place_label: Mapped[str] = mapped_column(String(120), nullable=False)
    reward: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Donor(Base):
    __tablename__ = "donors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[str] = mapped_column(String(120), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class RulesContent(Base):
    __tablename__ = "rules_content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    body: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ArchiveEntry(Base):
    __tablename__ = "archive_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    season: Mapped[str] = mapped_column(String(120), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    link_url: Mapped[str] = mapped_column(String(512), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ChatSetting(Base):
    __tablename__ = "chat_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=10)
    max_length: Mapped[int] = mapped_column(Integer, default=1000)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
