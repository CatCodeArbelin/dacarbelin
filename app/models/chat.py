"""Описывает модели и структуры данных для чата и сообщений."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    temp_nick: Mapped[str] = mapped_column(String(120), nullable=False)
    nick_color: Mapped[str] = mapped_column(String(7), default="#00d4ff")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False)
    sender_token: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
