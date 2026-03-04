"""Хранит снапшоты завершенных турниров для публичного архива."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TournamentArchive(Base):
    __tablename__ = "tournament_archives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    season: Mapped[str] = mapped_column(String(120), default="")
    winner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    winner_nickname: Mapped[str] = mapped_column(String(120), default="")
    bracket_payload_json: Mapped[str] = mapped_column(Text, default="")
    group_payload_json: Mapped[str] = mapped_column(Text, default="")
    source_tournament_version: Mapped[str] = mapped_column(String(64), default="legacy")
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
