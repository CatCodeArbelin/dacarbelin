from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Basket(str, Enum):
    INVITED = "invited"
    QUEEN_TOP = "queen_top"
    QUEEN = "queen"
    QUEEN_RESERVE = "queen_reserve"
    KING = "king"
    KING_RESERVE = "king_reserve"
    ROOK = "rook"
    ROOK_RESERVE = "rook_reserve"
    BISHOP = "bishop"
    BISHOP_RESERVE = "bishop_reserve"
    LOW_RANK = "low_rank"
    LOW_RANK_RESERVE = "low_rank_reserve"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nickname: Mapped[str] = mapped_column(String(120), nullable=False)
    steam_input: Mapped[str] = mapped_column(String(255), nullable=False)
    steam_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    game_nickname: Mapped[str] = mapped_column(String(255), nullable=False)
    current_rank: Mapped[str] = mapped_column(String(120), nullable=False)
    highest_rank: Mapped[str] = mapped_column(String(120), nullable=False)
    telegram: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discord: Mapped[str | None] = mapped_column(String(255), nullable=True)
    basket: Mapped[str] = mapped_column(String(50), default=Basket.LOW_RANK.value, index=True)
    extra_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
