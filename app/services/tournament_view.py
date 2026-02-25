"""Формирует view-model для отображения турнирной страницы."""

from typing import Mapping, Sequence, TypedDict

from app.models.tournament import GroupMember, PlayoffParticipant, PlayoffStage, TournamentGroup
from app.models.user import User
from app.services.i18n import t
from app.services.tournament import (
    build_stage_2_direct_invite_preview,
    get_stage_group_label,
    get_stage_group_number_by_seed,
    playoff_sort_key,
    sort_members_for_table,
)
from app.services.tournament_stage_config import (
    GROUP_STAGE_GAME_LIMIT,
    get_promote_top_n,
    is_limited_stage,
)


class GroupStageStandingRow(TypedDict):
    user_id: int
    display_nickname: str
    total_points: int
    first_places: int
    top4_finishes: int
    games_played: int
    top8_finishes: int
    eighth_places: int
    status: str


class BracketParticipantVM(TypedDict):
    user_id: int
    nickname: str
    is_direct_invite_preview: bool


class BracketMatchVM(TypedDict, total=False):
    group_label: str
    game_number: int
    schedule_text: str
    lobby_password: str
    participants: list[BracketParticipantVM]
    state: str
    is_preview: bool


class BracketColumnVM(TypedDict):
    key: str
    title: str
    matches: list[BracketMatchVM]


class PlayoffStandingRow(TypedDict):
    user_id: int
    display_nickname: str
    points: int
    wins: int
    top4_finishes: int
    games_played: int
    top8_finishes: int
    eighth_places: int
    status: str


class PlayoffStageStandingsVM(TypedDict):
    title: str
    participants: list[PlayoffStandingRow]


def _display_nickname(user: User | None, fallback: str) -> str:
    if not user:
        return fallback
    game_nickname = (user.game_nickname or "").strip()
    if game_nickname:
        return f"{user.nickname}({game_nickname})"
    return user.nickname


def _normalize_schedule(value: str | None) -> str:
    return (value or "").strip() or "TBD"


def build_group_stage_standings(groups: Sequence[TournamentGroup]) -> dict[int, list[GroupStageStandingRow]]:
    standings: dict[int, list[GroupStageStandingRow]] = {}
    for group in groups:
        ranked_members = sort_members_for_table(group.members)
        group_done = getattr(group, "current_game", 1) > 3
        rows: list[GroupStageStandingRow] = []
        for idx, member in enumerate(ranked_members, start=1):
            status = "normal"
            if group_done:
                status = "promoted" if idx <= 3 else "eliminated"
            rows.append(
                {
                    "user_id": member.user_id,
                    "display_nickname": _display_nickname(member.user, str(member.user_id)),
                    "total_points": member.total_points,
                    "first_places": member.first_places,
                    "top4_finishes": member.top4_finishes,
                    "games_played": member.top8_finishes,
                    "top8_finishes": member.top8_finishes,
                    "eighth_places": member.eighth_places,
                    "status": status,
                }
            )
        standings[group.id] = rows
    return standings


def _participants_for_group_members(members: Sequence[GroupMember]) -> list[BracketParticipantVM]:
    return [
        {
            "user_id": member.user_id,
            "nickname": _display_nickname(member.user, str(member.user_id)),
            "is_direct_invite_preview": False,
        }
        for member in sort_members_for_table(list(members))
    ]


def _participants_for_playoff_members(
    participants: Sequence[PlayoffParticipant], user_by_id: Mapping[int, User]
) -> dict[int, list[BracketParticipantVM]]:
    participants_by_group: dict[int, list[BracketParticipantVM]] = {}
    for participant in sorted(participants, key=lambda item: item.seed):
        group_number = get_stage_group_number_by_seed(participant.seed)
        user = user_by_id.get(participant.user_id)
        participants_by_group.setdefault(group_number, []).append(
            {
                "user_id": participant.user_id,
                "nickname": _display_nickname(user, str(participant.user_id)),
                "is_direct_invite_preview": False,
            }
        )
    return participants_by_group


def build_bracket_columns(
    groups: Sequence[TournamentGroup],
    playoff_stages: Sequence[PlayoffStage],
    user_by_id: Mapping[int, User],
    direct_invite_ids: list[int],
) -> list[BracketColumnVM]:
    def _empty_match(stage_key: str, group_number: int) -> BracketMatchVM:
        return {
            "group_label": get_stage_group_label(stage_key, group_number),
            "game_number": 1,
            "schedule_text": "TBD",
            "lobby_password": "TBD",
            "participants": [],
            "state": "pending",
        }

    stage_by_key = {stage.key: stage for stage in playoff_stages}
    stage_columns: list[BracketColumnVM] = [
        {"key": "group_stage", "title": "I этап", "matches": []},
        {"key": "stage_2", "title": "II этап (32)", "matches": []},
        {"key": "stage_1_4", "title": "III этап — полуфинальные группы (16)", "matches": []},
        {"key": "stage_final", "title": "Финал (8)", "matches": []},
    ]

    group_matches_vm: list[BracketMatchVM] = []
    for group in groups:
        raw_group_name = str(getattr(group, "name", "")).strip()
        fallback_label = str(getattr(group, "id", "?")).strip()
        group_name = raw_group_name or fallback_label
        current_game = getattr(group, "current_game", 1)
        state = "completed" if current_game > 3 else ("started" if getattr(group, "is_started", False) else "pending")
        group_matches_vm.append(
            {
                "group_label": get_stage_group_label("stage_2", int(group_name)) if group_name.isdigit() else group_name.replace("Group ", "").strip(),
                "game_number": 3 if current_game > 3 else current_game,
                "schedule_text": _normalize_schedule(getattr(group, "schedule_text", "TBD")),
                "lobby_password": getattr(group, "lobby_password", "TBD"),
                "participants": _participants_for_group_members(group.members),
                "state": state,
            }
        )
    known_group_labels = {match["group_label"] for match in group_matches_vm}
    for group_number in range(1, 8):
        label = get_stage_group_label("stage_2", group_number)
        if label in known_group_labels:
            continue
        group_matches_vm.append(_empty_match("stage_2", group_number))
    stage_columns[0]["matches"] = sorted(group_matches_vm, key=lambda item: item["group_label"])

    for column in stage_columns[1:]:
        stage = stage_by_key.get(column["key"])
        if not stage:
            if column["key"] == "stage_2":
                preview_direct_invites = build_stage_2_direct_invite_preview(direct_invite_ids)
                participants_by_group: dict[int, list[BracketParticipantVM]] = {}
                for invited in preview_direct_invites:
                    user = user_by_id.get(invited["user_id"])
                    participants_by_group.setdefault(invited["group_number"], []).append(
                        {
                            "user_id": invited["user_id"],
                            "nickname": _display_nickname(user, str(invited["user_id"])),
                            "is_direct_invite_preview": True,
                        }
                    )

                preview_matches_vm: list[BracketMatchVM] = []
                for group_number in range(1, 5):
                    placeholder = _empty_match("stage_2", group_number)
                    placeholder["participants"] = participants_by_group.get(group_number, [])
                    placeholder["is_preview"] = True
                    preview_matches_vm.append(placeholder)
                column["matches"] = preview_matches_vm
            if column["key"] == "stage_1_4":
                column["matches"] = [_empty_match("stage_1_4", group_number) for group_number in range(1, 3)]
            if column["key"] == "stage_final":
                placeholder = _empty_match("stage_final", 1)
                placeholder["group_label"] = "Final"
                column["matches"] = [placeholder]
            continue

        participants_by_group = _participants_for_playoff_members(stage.participants, user_by_id)
        matches_by_group = {match.group_number: match for match in sorted(stage.matches, key=lambda item: item.group_number)}

        stage_group_numbers = sorted({*participants_by_group.keys(), *matches_by_group.keys()})
        if is_limited_stage(stage.key):
            stage_size = getattr(stage, "stage_size", None) or 0
            if stage_size:
                stage_group_numbers = list(range(1, max(stage_size // 8, 0) + 1))

        matches_vm: list[BracketMatchVM] = []
        for group_number in stage_group_numbers:
            match = matches_by_group.get(group_number)
            if match is None:
                matches_vm.append(
                    {
                        "group_label": get_stage_group_label(stage.key, group_number),
                        "game_number": 1,
                        "schedule_text": "TBD",
                        "lobby_password": "TBD",
                        "participants": [],
                        "state": "pending",
                    }
                )
                continue

            matches_vm.append(
                {
                    "group_label": get_stage_group_label(stage.key, match.group_number),
                    "game_number": match.game_number,
                    "schedule_text": _normalize_schedule(match.schedule_text),
                    "lobby_password": match.lobby_password,
                    "participants": participants_by_group.get(match.group_number, []),
                    "state": match.state,
                }
            )
        column["matches"] = matches_vm

    return stage_columns


def build_playoff_standings(
    playoff_stages: Sequence[PlayoffStage], user_by_id: Mapping[int, User]
) -> list[PlayoffStageStandingsVM]:
    standings: list[PlayoffStageStandingsVM] = []
    for stage in playoff_stages:
        participants_sorted = sorted(stage.participants, key=playoff_sort_key, reverse=True)
        stage_group_done: set[int] = set()
        for match in stage.matches:
            if is_limited_stage(stage.key) and match.game_number > GROUP_STAGE_GAME_LIMIT:
                stage_group_done.add(match.group_number)

        promote_n = get_promote_top_n(stage.key)
        by_group_rank: dict[int, dict[int, int]] = {}
        for group_number in {get_stage_group_number_by_seed(p.seed) for p in participants_sorted}:
            group_sorted = [p for p in participants_sorted if get_stage_group_number_by_seed(p.seed) == group_number]
            by_group_rank[group_number] = {p.user_id: idx for idx, p in enumerate(group_sorted, start=1)}

        rows: list[PlayoffStandingRow] = []
        for participant in participants_sorted:
            group_number = get_stage_group_number_by_seed(participant.seed)
            status = "normal"
            if group_number in stage_group_done and promote_n > 0:
                rank = by_group_rank[group_number].get(participant.user_id, 99)
                status = "promoted" if rank <= promote_n else "eliminated"

            rows.append(
                {
                    "user_id": participant.user_id,
                    "display_nickname": _display_nickname(user_by_id.get(participant.user_id), str(participant.user_id)),
                    "points": participant.points,
                    "wins": participant.wins,
                    "top4_finishes": participant.top4_finishes,
                    "games_played": participant.top8_finishes,
                    "top8_finishes": participant.top8_finishes,
                    "eighth_places": getattr(participant, "eighth_places", 0),
                    "status": status,
                }
            )
        standings.append({"title": stage.title, "participants": rows})

    return standings


def resolve_current_stage_label(lang: str, playoff_stages: Sequence[PlayoffStage], show_playoff: bool) -> str:
    stage_display_key_by_stage_key = {
        "group_stage": "tournament_stage_group_stage_label",
        "stage_2": "tournament_stage_1_4_label",
        "stage_1_8": "tournament_stage_1_8_label",
        "stage_1_4": "tournament_stage_semifinal_groups_label",
        "stage_final": "tournament_stage_final_label",
    }

    default_display = t(lang, stage_display_key_by_stage_key["group_stage"])
    if not show_playoff:
        return default_display

    active_playoff = next((stage for stage in playoff_stages if stage.is_started), None)
    current_stage = active_playoff or (playoff_stages[0] if playoff_stages else None)
    if current_stage is None:
        return default_display

    display_key = stage_display_key_by_stage_key.get(current_stage.key)
    if display_key is not None:
        return t(lang, display_key)

    return current_stage.title or default_display
