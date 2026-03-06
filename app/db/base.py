"""Регистрирует ORM-модели в метаданных SQLAlchemy."""

from app.models.chat import ChatMessage
from app.models.settings import (
    ArchiveEntry,
    ChatSetting,
    DonationLink,
    DonationMethod,
    CryptoWallet,
    Donor,
    PrizePoolEntry,
    RulesContent,
    SiteSetting,
    TournamentStage,
)
from app.models.tournament import EmergencyOperationLog, GroupGameResult, GroupManualTieBreak, GroupMember, TournamentGroup
from app.models.tournament_archive import TournamentArchive
from app.models.user import User

__all__ = [
    "User",
    "TournamentStage",
    "SiteSetting",
    "DonationLink",
    "DonationMethod",
    "CryptoWallet",
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
    "EmergencyOperationLog",
    "TournamentArchive",
]
