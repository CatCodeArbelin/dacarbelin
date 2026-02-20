from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.user import User

from app.models.base import Base


class TournamentGroup(Base):
    __tablename__ = "tournament_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage: Mapped[str] = mapped_column(String(50), default="group_stage", index=True)
    name: Mapped[str] = mapped_column(String(50), index=True)
    lobby_password: Mapped[str] = mapped_column(String(4), default="0000")
    current_game: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    members: Mapped[list["GroupMember"]] = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("tournament_groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    seat: Mapped[int] = mapped_column(Integer, default=0)
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    first_places: Mapped[int] = mapped_column(Integer, default=0)
    top4_finishes: Mapped[int] = mapped_column(Integer, default=0)
    eighth_places: Mapped[int] = mapped_column(Integer, default=0)
    last_game_place: Mapped[int] = mapped_column(Integer, default=8)

    group: Mapped[TournamentGroup] = relationship("TournamentGroup", back_populates="members")
    user: Mapped[User] = relationship("User")


class GroupGameResult(Base):
    __tablename__ = "group_game_results"
    __table_args__ = (UniqueConstraint("group_id", "game_number", "place", name="uq_group_game_place"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("tournament_groups.id", ondelete="CASCADE"), index=True)
    game_number: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    place: Mapped[int] = mapped_column(Integer)
    points_awarded: Mapped[int] = mapped_column(Integer)
