from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.user import User

from app.models.base import Base


class TournamentGroup(Base):
    __tablename__ = "tournament_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage: Mapped[str] = mapped_column(String(50), default="group_stage", index=True)
    name: Mapped[str] = mapped_column(String(50), index=True)
    lobby_password: Mapped[str] = mapped_column(String(4), default="0000")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    schedule_text: Mapped[str] = mapped_column(String(120), default="TBD")
    current_game: Mapped[int] = mapped_column(Integer, default=1)
    is_started: Mapped[bool] = mapped_column(Boolean, default=False)
    draw_mode: Mapped[str] = mapped_column(String(20), default="auto")
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


class GroupManualTieBreak(Base):
    __tablename__ = "group_manual_tie_breaks"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_manual_tie_break_user"),
        UniqueConstraint("group_id", "priority", name="uq_group_manual_tie_break_priority"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("tournament_groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    priority: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PlayoffStage(Base):
    __tablename__ = "playoff_stages"
    __table_args__ = (UniqueConstraint("key", name="uq_playoff_stage_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(100))
    stage_size: Mapped[int] = mapped_column(Integer)
    stage_order: Mapped[int] = mapped_column(Integer, index=True)
    scoring_mode: Mapped[str] = mapped_column(String(32), default="standard")
    stage_code: Mapped[str] = mapped_column(String(20), default="playoff")
    is_started: Mapped[bool] = mapped_column(Boolean, default=False)
    final_candidate_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    matches: Mapped[list["PlayoffMatch"]] = relationship("PlayoffMatch", back_populates="stage", cascade="all, delete-orphan")
    participants: Mapped[list["PlayoffParticipant"]] = relationship(
        "PlayoffParticipant",
        back_populates="stage",
        cascade="all, delete-orphan",
    )


class PlayoffParticipant(Base):
    __tablename__ = "playoff_participants"
    __table_args__ = (UniqueConstraint("stage_id", "user_id", name="uq_playoff_stage_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("playoff_stages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    top4_finishes: Mapped[int] = mapped_column(Integer, default=0)
    last_place: Mapped[int] = mapped_column(Integer, default=8)
    is_eliminated: Mapped[bool] = mapped_column(Boolean, default=False)

    stage: Mapped[PlayoffStage] = relationship("PlayoffStage", back_populates="participants")
    user: Mapped[User] = relationship("User")


class PlayoffMatch(Base):
    __tablename__ = "playoff_matches"
    __table_args__ = (UniqueConstraint("stage_id", "match_number", name="uq_playoff_stage_match_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("playoff_stages.id", ondelete="CASCADE"), index=True)
    match_number: Mapped[int] = mapped_column(Integer, index=True)
    group_number: Mapped[int] = mapped_column(Integer, default=1, index=True)
    game_number: Mapped[int] = mapped_column(Integer, default=1)
    lobby_password: Mapped[str] = mapped_column(String(4), default="0000")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    schedule_text: Mapped[str] = mapped_column(String(120), default="TBD")
    state: Mapped[str] = mapped_column(String(20), default="pending")
    winner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    manual_winner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    manual_override_note: Mapped[str] = mapped_column(String(255), default="")

    stage: Mapped[PlayoffStage] = relationship("PlayoffStage", back_populates="matches")
