"""Регистрирует ORM-модели в метаданных SQLAlchemy."""

from app.models.chat import ChatMessage
from app.models.settings import (
    ArchiveEntry,
    ChatSetting,
    DonationLink,
    DonationMethod,
    Donor,
    PrizePoolEntry,
    RulesContent,
    SiteSetting,
    TournamentStage,
)
from app.models.tournament import GroupGameResult, GroupManualTieBreak, GroupMember, TournamentGroup
from app.models.user import User

__all__ = [
    "User",
    "TournamentStage",
    "SiteSetting",
    "DonationLink",
    "DonationMethod",
    "PrizePoolEntry",
    "Donor",
    "RulesContent",
    "ArchiveEntry",
    "ChatSetting",
    "ChatMessage",
    "TournamentGroup",
    "GroupMember",
    "GroupGameResult",
    "GroupManualTieBreak",
]
