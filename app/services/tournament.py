"""Реализует основную бизнес-логику управления турниром и сеткой матчей."""

from collections import defaultdict
import json
import random

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.settings import SiteSetting
from app.models.tournament_archive import TournamentArchive
from app.models.tournament import (
    GroupGameResult,
    GroupManualTieBreak,
    GroupMember,
    PlayoffMatch,
    PlayoffParticipant,
    PlayoffStage,
    TournamentGroup,
)
from app.models.user import Basket, User
from app.services.tournament_stage_config import (
    DEFAULT_TOURNAMENT_PROFILE_KEY,
    FINAL_STAGE_SCORING_MODES,
    GROUP_STAGE_GAME_LIMIT,
    TOURNAMENT_FLOW_SPEC,
    get_tournament_profile_spec,
    get_promote_top_n,
    get_stage_group_count,
    get_stage_group_label as get_stage_group_label_from_spec,
    is_final_stage_key,
    is_limited_stage,
)

POINTS_BY_PLACE = {1: 8, 2: 6, 3: 5, 4: 4, 5: 3, 6: 2, 7: 1, 8: 0}
PRIMARY_BASKETS = [
    Basket.QUEEN_TOP.value,
    Basket.QUEEN.value,
    Basket.QUEEN_RESERVE.value,
    Basket.KING.value,
    Basket.KING_RESERVE.value,
    Basket.ROOK.value,
    Basket.ROOK_RESERVE.value,
    Basket.BISHOP.value,
    Basket.BISHOP_RESERVE.value,
    Basket.LOW_RANK.value,
    Basket.LOW_RANK_RESERVE.value,
]

PRIMARY_DRAW_BASKETS_WITH_RESERVE = {
    Basket.QUEEN.value: Basket.QUEEN_RESERVE.value,
    Basket.KING.value: Basket.KING_RESERVE.value,
    Basket.ROOK.value: Basket.ROOK_RESERVE.value,
    Basket.BISHOP.value: Basket.BISHOP_RESERVE.value,
}


class ManualDrawValidationError(ValueError):
    def __init__(self, details: str):
        super().__init__(details)
        self.details = details


def generate_password() -> str:
    # Генерируем четырехзначный пароль лобби.
    return f"{random.randint(0, 9999):04d}"


async def clear_group_stage(db: AsyncSession) -> None:
    # Полностью очищаем текущую групповую стадию.
    group_ids = list((await db.scalars(select(TournamentGroup.id).where(TournamentGroup.stage == "group_stage"))).all())
    if group_ids:
        await db.execute(delete(GroupGameResult).where(GroupGameResult.group_id.in_(group_ids)))
        await db.execute(delete(GroupMember).where(GroupMember.group_id.in_(group_ids)))
        await db.execute(delete(TournamentGroup).where(TournamentGroup.id.in_(group_ids)))


async def create_auto_draw(db: AsyncSession) -> tuple[bool, str]:
    """Создает автоматическую жеребьевку для стартового этапа по активному профилю."""
    users = list(
        (
            await db.scalars(
                select(User)
                .where(User.basket.in_(PRIMARY_BASKETS))
                .order_by(User.created_at)
            )
        ).all()
    )
    profile_spec = await get_current_tournament_profile_spec(db)
    expected_group_count = int(profile_spec["stage_1_groups_count"])
    stage_group_size = int(TOURNAMENT_FLOW_SPEC["group_stage"]["group_size"])
    expected_participants = expected_group_count * stage_group_size

    if len(users) < expected_participants:
        return False, (
            "Автожеребьевка недоступна: требуется минимум "
            f"{expected_participants} валидных участников (формат {expected_group_count}x{stage_group_size}). "
            "Доступна только ручная жеребьевка."
        )

    try:
        await clear_group_stage(db)
        by_basket: dict[str, list[User]] = defaultdict(list)
        for user in users:
            by_basket[user.basket].append(user)

        for bucket in by_basket.values():
            random.shuffle(bucket)

        assigned_by_group: list[list[User]] = []
        for _ in range(expected_group_count):
            picked: list[User] = []
            for basket, reserve_basket in PRIMARY_DRAW_BASKETS_WITH_RESERVE.items():
                for _ in range(2):
                    source_basket = basket
                    if not by_basket[source_basket] and by_basket[reserve_basket]:
                        source_basket = reserve_basket

                    if by_basket[source_basket]:
                        picked.append(by_basket[source_basket].pop())
                if len(picked) >= stage_group_size:
                    break

            fallback_pool: list[User] = []
            for basket in PRIMARY_BASKETS:
                if basket == Basket.INVITED.value:
                    continue
                fallback_pool.extend(by_basket[basket])
            random.shuffle(fallback_pool)
            while len(picked) < stage_group_size and fallback_pool:
                candidate = fallback_pool.pop()
                if candidate not in picked and candidate in by_basket[candidate.basket]:
                    by_basket[candidate.basket].remove(candidate)
                    picked.append(candidate)

            unique_ids = {player.id for player in picked}
            if len(picked) != stage_group_size or len(unique_ids) != stage_group_size:
                raise ValueError(
                    "Не удалось собрать "
                    f"{stage_group_size} уникальных участников для группы в формате {expected_group_count}x{stage_group_size}. "
                    "Доступна только ручная жеребьевка."
                )

            assigned_by_group.append(picked)

        assigned_players_count = sum(len(group_players) for group_players in assigned_by_group)
        if len(assigned_by_group) != expected_group_count or assigned_players_count != expected_participants:
            raise ValueError(
                "Итоговая автожеребьевка невалидна: требуется ровно "
                f"{expected_group_count} групп и {expected_participants} назначенных участников "
                f"({expected_group_count}x{stage_group_size}). Доступна только ручная жеребьевка."
            )

        groups: list[TournamentGroup] = []
        for idx in range(expected_group_count):
            group = TournamentGroup(
                name=f"Group {chr(65 + idx)}",
                lobby_password=generate_password(),
                schedule_text="TBD",
            )
            db.add(group)
            groups.append(group)
        await db.flush()

        for group, players in zip(groups, assigned_by_group, strict=True):
            for seat, player in enumerate(players, start=1):
                db.add(GroupMember(group_id=group.id, user_id=player.id, seat=seat))

        await db.commit()
        return True, "Автоматическая жеребьевка успешно создана"
    except ValueError as exc:
        await db.rollback()
        return False, str(exc)


async def _require_group(db: AsyncSession, group_id: int) -> TournamentGroup:
    group = await db.scalar(select(TournamentGroup).where(TournamentGroup.id == group_id))
    if not group:
        raise ValueError("Group not found")
    return group


async def validate_group_member_constraints(
    db: AsyncSession,
    *,
    group_id: int,
    user_id: int,
    ignore_member_ids: set[int] | None = None,
) -> TournamentGroup:
    """Проверяем лимит 8 участников в группе и уникальность игрока в рамках стадии."""
    group = await _require_group(db, group_id)

    user = await db.scalar(select(User.id).where(User.id == user_id))
    if not user:
        raise ValueError("User not found")

    ignored_ids = ignore_member_ids or set()

    group_member_exists = await db.scalar(
        select(GroupMember.id).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
    )
    if group_member_exists and group_member_exists not in ignored_ids:
        raise ValueError("Игрок уже есть в этой группе")

    stage_group_ids = list(
        (
            await db.scalars(select(TournamentGroup.id).where(TournamentGroup.stage == group.stage))
        ).all()
    )
    stage_member_ids = list(
        (
            await db.scalars(
                select(GroupMember.id)
                .where(
                    GroupMember.group_id.in_(stage_group_ids),
                    GroupMember.user_id == user_id,
                )
            )
        ).all()
    )
    if ignored_ids:
        stage_member_ids = [member_id for member_id in stage_member_ids if member_id not in ignored_ids]
    if stage_member_ids:
        raise ValueError("Игрок уже находится в другой группе этой стадии")

    member_count = len(list((await db.scalars(select(GroupMember.id).where(GroupMember.group_id == group_id))).all()))
    if ignored_ids:
        member_count -= len([member_id for member_id in ignored_ids if member_id])
    if member_count >= 8:
        raise ValueError("Группа уже заполнена (максимум 8 участников)")

    return group


def parse_manual_draw_user_ids(raw_user_ids: str | list[str] | tuple[str, ...] | None) -> list[int]:
    if raw_user_ids is None:
        raise ValueError("Список ID участников обязателен")

    if isinstance(raw_user_ids, str):
        parts = [part.strip() for part in raw_user_ids.split(",") if part.strip()]
    else:
        parts = [str(part).strip() for part in raw_user_ids if str(part).strip()]

    if not parts:
        return []

    try:
        parsed = [int(part) for part in parts]
    except (TypeError, ValueError) as exc:
        raise ValueError("ID участников должны быть целыми числами") from exc

    if len(parsed) != len(set(parsed)):
        raise ValueError("ID участников в ручной жеребьевке должны быть уникальны")
    return parsed


async def create_manual_draw(
    db: AsyncSession,
    group_count: int,
    user_ids: list[int],
    layout_by_group: list[list[int]] | None = None,
) -> None:
    if group_count < 1 or group_count > 8:
        raise ValueError("Количество групп должно быть от 1 до 8")
    if len(user_ids) > group_count * 8:
        raise ValueError("Слишком много участников для выбранного числа групп")

    await clear_group_stage(db)
    groups: list[TournamentGroup] = []
    for idx in range(group_count):
        group = TournamentGroup(
            name=f"Group {chr(65 + idx)}",
            lobby_password=generate_password(),
            schedule_text="TBD",
            draw_mode="manual",
        )
        db.add(group)
        groups.append(group)
    await db.flush()

    if layout_by_group is not None:
        if len(layout_by_group) != group_count:
            raise ValueError("Количество групп в раскладке не совпадает с group_count")

        for members in layout_by_group:
            if len(members) > 8:
                raise ValueError("Группа уже заполнена (максимум 8 участников)")

        flattened_ids = [user_id for members in layout_by_group for user_id in members]
        if len(flattened_ids) != len(set(flattened_ids)):
            raise ValueError("ID участников в раскладке должны быть уникальны")

        for group, members in zip(groups, layout_by_group, strict=True):
            for seat, user_id in enumerate(members, start=1):
                await validate_group_member_constraints(db, group_id=group.id, user_id=user_id)
                db.add(GroupMember(group_id=group.id, user_id=user_id, seat=seat))
    else:
        for offset, user_id in enumerate(user_ids):
            group = groups[offset % group_count]
            await validate_group_member_constraints(db, group_id=group.id, user_id=user_id)
            seat = 1 + len(list((await db.scalars(select(GroupMember.id).where(GroupMember.group_id == group.id))).all()))
            db.add(GroupMember(group_id=group.id, user_id=user_id, seat=seat))

    await db.commit()


def _normalize_manual_layout_payload(layout_payload: object) -> list[list[int]]:
    if isinstance(layout_payload, dict):
        groups_payload = layout_payload.get("groups")
        group_order_payload = layout_payload.get("group_order")
        if not isinstance(groups_payload, list) or not groups_payload:
            raise ManualDrawValidationError("invalid_layout")

        groups_by_index: dict[int, list[int]] = {}
        for group_payload in groups_payload:
            if not isinstance(group_payload, dict):
                raise ManualDrawValidationError("invalid_layout")
            group_index = group_payload.get("group_index")
            members = group_payload.get("members")
            if not isinstance(group_index, int) or group_index < 0 or not isinstance(members, list):
                raise ManualDrawValidationError("invalid_layout")
            if group_index in groups_by_index:
                raise ManualDrawValidationError("invalid_layout")
            groups_by_index[group_index] = members

        if isinstance(group_order_payload, list) and group_order_payload:
            if len(group_order_payload) != len(groups_by_index):
                raise ManualDrawValidationError("invalid_layout")
            try:
                group_order = [int(item) for item in group_order_payload]
            except (TypeError, ValueError) as exc:
                raise ManualDrawValidationError("invalid_layout") from exc
            if len(group_order) != len(set(group_order)):
                raise ManualDrawValidationError("invalid_layout")
            if any(index not in groups_by_index for index in group_order):
                raise ManualDrawValidationError("invalid_layout")
            return [groups_by_index[index] for index in group_order]

        return [groups_by_index[index] for index in sorted(groups_by_index)]

    if isinstance(layout_payload, list):
        return layout_payload

    raise ManualDrawValidationError("invalid_layout")


async def create_manual_draw_from_layout(db: AsyncSession, layout_payload: object) -> None:
    layout = _normalize_manual_layout_payload(layout_payload)
    if not layout:
        raise ManualDrawValidationError("invalid_layout")

    group_count = len(layout)
    if group_count < 1 or group_count > 8:
        raise ManualDrawValidationError("invalid_layout")

    seen_user_ids: set[int] = set()
    normalized_layout: list[list[int]] = []
    for members in layout:
        if not isinstance(members, list):
            raise ManualDrawValidationError("invalid_layout")
        if len(members) > 8:
            raise ManualDrawValidationError("group_overflow")

        try:
            parsed_members = parse_manual_draw_user_ids(members)
        except ValueError as exc:
            raise ManualDrawValidationError("invalid_layout") from exc

        for user_id in parsed_members:
            if user_id in seen_user_ids:
                raise ManualDrawValidationError(f"duplicate_user:{user_id}")
            seen_user_ids.add(user_id)

        normalized_layout.append(parsed_members)

    await clear_group_stage(db)
    groups: list[TournamentGroup] = []
    for idx in range(group_count):
        group = TournamentGroup(
            name=f"Group {chr(65 + idx)}",
            lobby_password=generate_password(),
            schedule_text="TBD",
            draw_mode="manual",
        )
        db.add(group)
        groups.append(group)
    await db.flush()

    for group, members in zip(groups, normalized_layout, strict=True):
        for seat, user_id in enumerate(members, start=1):
            await validate_group_member_constraints(db, group_id=group.id, user_id=user_id)
            db.add(GroupMember(group_id=group.id, user_id=user_id, seat=seat))

    await db.commit()

def sort_members_for_table(members: list[GroupMember]) -> list[GroupMember]:
    # Сортируем таблицу по очкам и стабильным правилам. Финальный ключ — user_id для детерминированности.
    return sorted(
        members,
        key=lambda m: (
            -m.total_points,
            -m.first_places,
            -m.top4_finishes,
            -m.top8_finishes,
            m.eighth_places,
            m.last_game_place,
            m.user_id,
        ),
    )


async def apply_game_results(db: AsyncSession, group_id: int, ordered_user_ids: list[int]) -> None:
    """Проставляет результаты одной игры и пересчитывает агрегаты участникам группы."""
    group = await db.scalar(select(TournamentGroup).where(TournamentGroup.id == group_id))
    if not group:
        raise ValueError("Group not found")
    if len(ordered_user_ids) != 8 or len(set(ordered_user_ids)) != 8:
        raise ValueError("Нужно передать ровно 8 уникальных id участников")

    members = list((await db.scalars(select(GroupMember).where(GroupMember.group_id == group_id))).all())
    members_by_user = {m.user_id: m for m in members}
    for uid in ordered_user_ids:
        if uid not in members_by_user:
            raise ValueError("В результатах есть игрок, которого нет в группе")

    game_number = group.current_game
    existing = await db.scalar(
        select(GroupGameResult).where(GroupGameResult.group_id == group_id, GroupGameResult.game_number == game_number)
    )
    if existing:
        raise ValueError("Для текущей игры результаты уже внесены")

    for place, user_id in enumerate(ordered_user_ids, start=1):
        points = POINTS_BY_PLACE[place]
        db.add(GroupGameResult(group_id=group_id, game_number=game_number, user_id=user_id, place=place, points_awarded=points))
        member = members_by_user[user_id]
        member.total_points += points
        member.first_places += 1 if place == 1 else 0
        member.top4_finishes += 1 if place <= 4 else 0
        member.top8_finishes = (member.top8_finishes or 0) + 1
        member.eighth_places += 1 if place == 8 else 0
        member.last_game_place = place

    if group.current_game <= GROUP_STAGE_GAME_LIMIT:
        group.current_game += 1
    await db.commit()


PLAYOFF_STAGE_SEQUENCE = [
    (
        stage_key,
        str(stage_spec["admin_title"]),
        int(stage_spec["participants"]),
        str(stage_spec["scoring_mode"]),
    )
    for stage_key, stage_spec in TOURNAMENT_FLOW_SPEC.items()
    if stage_key != "group_stage"
]
PLAYOFF_STAGE_COLUMNS = [
    (stage_key, str(stage_spec["column_title"]))
    for stage_key, stage_spec in TOURNAMENT_FLOW_SPEC.items()
    if stage_key != "group_stage"
]
FINAL_SCORING_MODE = str(TOURNAMENT_FLOW_SPEC["stage_final"]["scoring_mode"])
DIRECT_INVITE_STAGE_2 = "stage_2"


async def get_current_tournament_profile_key(db: AsyncSession) -> str:
    if hasattr(db, "scalar"):
        profile_row = await db.scalar(select(SiteSetting).where(SiteSetting.key == "tournament_profile"))
    else:
        profile_rows = list((await db.scalars(select(SiteSetting).where(SiteSetting.key == "tournament_profile"))).all())
        profile_row = profile_rows[0] if profile_rows else None
    return (profile_row.value or DEFAULT_TOURNAMENT_PROFILE_KEY) if profile_row else DEFAULT_TOURNAMENT_PROFILE_KEY


async def get_current_tournament_profile_spec(db: AsyncSession) -> dict[str, int | str]:
    profile_key = await get_current_tournament_profile_key(db)
    profile_spec = get_tournament_profile_spec(profile_key)
    return {
        "key": str(profile_spec["key"]),
        "stage_1_groups_count": int(profile_spec["stage_1_groups_count"]),
        "stage_1_promoted_count": int(profile_spec["stage_1_promoted_count"]),
        "stage_2_size": int(profile_spec["stage_2_size"]),
    }


def get_playoff_stage_sequence_keys() -> list[str]:
    return [key for key, *_ in PLAYOFF_STAGE_SEQUENCE]


def get_public_stage_display_sequence() -> list[str]:
    return ["group_stage", *get_playoff_stage_sequence_keys()]


def get_playoff_stage_columns() -> list[tuple[str, str]]:
    return list(PLAYOFF_STAGE_COLUMNS)


def get_playoff_stage_blueprint(usable_count: int) -> list[tuple[str, str, int, str]]:
    if usable_count >= PLAYOFF_STAGE_SEQUENCE[0][2]:
        return PLAYOFF_STAGE_SEQUENCE
    return []


def playoff_sort_key(participant: PlayoffParticipant) -> tuple[int, int, int, int, int, int]:
    return (
        participant.points,
        participant.wins,
        participant.top4_finishes,
        participant.top8_finishes,
        -participant.last_place,
        -participant.user_id,
    )


def playoff_tie_key(participant: PlayoffParticipant) -> tuple[int, int, int, int, int]:
    """Ключ равенства результатов без учета seed (seed используется только как стабильный fallback)."""
    return (
        participant.points,
        participant.wins,
        participant.top4_finishes,
        participant.top8_finishes,
        -participant.last_place,
    )


def apply_points_to_playoff_participant(participant: PlayoffParticipant, place: int, scoring_mode: str) -> None:
    participant.points += POINTS_BY_PLACE[place]
    if place == 1:
        participant.wins += 1
    if place <= 4:
        participant.top4_finishes += 1
    participant.top8_finishes = (participant.top8_finishes or 0) + 1
    participant.eighth_places = (participant.eighth_places or 0) + (1 if place == 8 else 0)
    participant.last_place = place


def get_group_count_for_stage(stage_size: int, stage_key: str | None = None) -> int:
    if stage_key:
        configured_groups_count = get_stage_group_count(stage_key)
        if configured_groups_count is not None:
            return configured_groups_count
    return max(1, stage_size // 8)


def get_promoted_count_for_stage(stage: PlayoffStage) -> int:
    promote_top_n = get_promote_top_n(stage.key)
    if not promote_top_n:
        return 0

    groups_count = get_group_count_for_stage(stage.stage_size, stage.key)
    return groups_count * promote_top_n


def get_stage_group_number_by_seed(seed: int) -> int:
    return ((seed - 1) // 8) + 1


def get_stage_group_label(stage_key: str, group_number: int) -> str:
    return get_stage_group_label_from_spec(stage_key, group_number)


def build_stage_2_player_ids(
    stage_1_promoted_ids: list[int],
    direct_invite_ids: list[int],
    *,
    promoted_target_count: int | None = None,
    stage_2_size: int | None = None,
    direct_invite_groups: dict[int, int] | None = None,
) -> list[int]:
    profile_spec = get_tournament_profile_spec()
    promoted_target_count = int(promoted_target_count or profile_spec["stage_1_promoted_count"])
    stage_2_size = int(stage_2_size or profile_spec["stage_2_size"])
    if len(stage_1_promoted_ids) != promoted_target_count:
        raise ValueError(f"Во II этап должны проходить ровно {promoted_target_count} участников из I этапа")

    required_invites = stage_2_size - len(stage_1_promoted_ids)
    if required_invites < 0:
        raise ValueError(f"Количество участников I этапа не может превышать размер II этапа ({stage_2_size})")
    if len(direct_invite_ids) > required_invites:
        raise ValueError(f"Нельзя превысить {required_invites} прямых инвайтов во II этап")

    if len(direct_invite_ids) < required_invites:
        raise ValueError(f"Для II этапа требуется минимум {required_invites} прямых инвайтов")

    direct_invite_ids = direct_invite_ids[:required_invites]

    promoted_set = set(stage_1_promoted_ids)
    direct_set = set(direct_invite_ids)
    if len(promoted_set) != len(stage_1_promoted_ids) or len(direct_set) != len(direct_invite_ids):
        raise ValueError("В списках участников обнаружены дубликаты")
    if promoted_set.intersection(direct_set):
        raise ValueError("Игрок не может быть одновременно прошедшим и прямым инвайтом")

    stage_2_player_ids: list[int | None] = [None] * stage_2_size
    stage_group_count = get_group_count_for_stage(stage_2_size, "stage_2")
    stage_group_size = max(1, stage_2_size // max(1, stage_group_count))

    for user_id in direct_invite_ids:
        group_number = (direct_invite_groups or {}).get(user_id)
        if group_number is None:
            continue
        if group_number < 1 or group_number > stage_group_count:
            raise ValueError("Некорректная группа прямого инвайта")

        group_start = (group_number - 1) * stage_group_size
        group_end = min(group_start + stage_group_size, stage_2_size)
        target_index = next((idx for idx in range(group_start, group_end) if stage_2_player_ids[idx] is None), None)
        if target_index is None:
            raise ValueError(f"Группа {group_number} переполнена прямыми инвайтами")
        stage_2_player_ids[target_index] = user_id

    staged_user_ids = [
        *stage_1_promoted_ids,
        *[user_id for user_id in direct_invite_ids if user_id not in set(stage_2_player_ids)],
    ]
    staged_index = 0
    for idx, current in enumerate(stage_2_player_ids):
        if current is not None:
            continue
        stage_2_player_ids[idx] = staged_user_ids[staged_index]
        staged_index += 1

    stage_2_player_ids = [int(user_id) for user_id in stage_2_player_ids]
    if len(stage_2_player_ids) != stage_2_size:
        raise ValueError(f"Во II этапе должно быть ровно {stage_2_size} участников")
    return stage_2_player_ids


def build_stage_2_direct_invite_preview(
    direct_invite_ids: list[int],
    *,
    promoted_count: int | None = None,
    stage_2_size: int | None = None,
    direct_invite_groups: dict[int, int] | None = None,
) -> list[dict[str, int]]:
    """Строит preview по прямым инвайтам во II этап с теми же seed, что и при генерации этапа."""
    profile_spec = get_tournament_profile_spec()
    promoted_count = int(promoted_count or profile_spec["stage_1_promoted_count"])
    stage_2_size = int(stage_2_size or profile_spec["stage_2_size"])
    required_invites = max(0, stage_2_size - promoted_count)
    seed_start = promoted_count + 1
    stage_group_count = get_group_count_for_stage(stage_2_size, "stage_2")
    stage_group_size = max(1, stage_2_size // max(1, stage_group_count))
    taken_seeds: set[int] = set()
    preview: list[dict[str, int]] = []
    for index, user_id in enumerate(direct_invite_ids[:required_invites]):
        preferred_group = (direct_invite_groups or {}).get(user_id)
        if preferred_group and 1 <= preferred_group <= stage_group_count:
            group_seed_start = (preferred_group - 1) * stage_group_size + 1
            group_seed_end = min(group_seed_start + stage_group_size - 1, stage_2_size)
            seed = next((candidate for candidate in range(group_seed_start, group_seed_end + 1) if candidate not in taken_seeds), seed_start + index)
        else:
            seed = seed_start + index
            while seed in taken_seeds and seed <= stage_2_size:
                seed += 1
            if seed > stage_2_size:
                seed = seed_start + index
                while seed in taken_seeds:
                    seed += 1

        taken_seeds.add(seed)
        preview.append(
            {
                "user_id": user_id,
                "seed": seed,
                "group_number": get_stage_group_number_by_seed(seed),
            }
        )
    return preview


def split_participants_by_group(participants: list[PlayoffParticipant]) -> dict[int, list[PlayoffParticipant]]:
    grouped: dict[int, list[PlayoffParticipant]] = defaultdict(list)
    for participant in participants:
        grouped[get_stage_group_number_by_seed(participant.seed)].append(participant)
    return grouped


async def shuffle_stage_2_participants(db: AsyncSession) -> None:
    stage_2 = await db.scalar(select(PlayoffStage).where(PlayoffStage.key == "stage_2"))
    if not stage_2:
        raise ValueError("Этап stage_2 не найден")

    stage_2_matches = list((await db.scalars(select(PlayoffMatch).where(PlayoffMatch.stage_id == stage_2.id))).all())
    if not stage_2_matches:
        raise ValueError("Матчи stage_2 не найдены")

    has_played_games = any(
        match.game_number != 1
        or match.state != "pending"
        or match.winner_user_id is not None
        or match.manual_winner_user_id is not None
        for match in stage_2_matches
    )
    if has_played_games:
        raise ValueError("После старта игр stage_2 пересидирование запрещено")

    participants = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_2.id))).all())
    if len(participants) != stage_2.stage_size:
        raise ValueError("Для пересидирования stage_2 требуется полный состав из 32 участников")

    shuffled_seeds = list(range(1, stage_2.stage_size + 1))
    random.shuffle(shuffled_seeds)
    for participant, seed in zip(participants, shuffled_seeds, strict=True):
        participant.seed = seed

    await db.commit()


async def rebuild_playoff_stages(db: AsyncSession, player_ids: list[int], *, stage_2_size: int) -> list[PlayoffStage]:
    usable_count = len(player_ids)
    stages_to_create = get_playoff_stage_blueprint(stage_2_size)
    if not stages_to_create:
        raise ValueError("Недостаточно игроков для playoff-этапов")

    await db.execute(delete(PlayoffMatch))
    await db.execute(delete(PlayoffParticipant))
    await db.execute(delete(PlayoffStage))

    stages: list[PlayoffStage] = []
    for order, (key, title, size, scoring_mode) in enumerate(stages_to_create):
        stage = PlayoffStage(
            key=key,
            title=title,
            stage_size=size,
            stage_order=order,
            scoring_mode=scoring_mode,
            stage_code=key,
            is_started=False,
        )
        db.add(stage)
        stages.append(stage)
    await db.flush()

    first_stage = stages[0]
    seeded = player_ids[: first_stage.stage_size]
    for seed, user_id in enumerate(seeded, start=1):
        db.add(PlayoffParticipant(stage_id=first_stage.id, user_id=user_id, seed=seed))

    for index, stage in enumerate(stages):
        if index == 0:
            groups_count = get_group_count_for_stage(len(seeded))
        else:
            groups_count = get_group_count_for_stage(stage.stage_size, stage.key)

        for group_number in range(1, groups_count + 1):
            db.add(
                PlayoffMatch(
                    stage_id=stage.id,
                    match_number=group_number,
                    group_number=group_number,
                    game_number=1,
                    lobby_password=generate_password(),
                    schedule_text="TBD",
                )
            )

    await db.commit()
    return stages


async def generate_playoff_from_groups(db: AsyncSession) -> tuple[bool, str]:
    profile_spec = await get_current_tournament_profile_spec(db)
    expected_stage_1_groups = int(profile_spec["stage_1_groups_count"])
    expected_promoted_count = int(profile_spec["stage_1_promoted_count"])
    stage_2_size = int(profile_spec["stage_2_size"])

    groups = list((await db.scalars(select(TournamentGroup).where(TournamentGroup.stage == "group_stage"))).all())
    if not groups:
        return False, "Сначала требуется сформировать групповой этап"

    if len(groups) != expected_stage_1_groups:
        return False, f"Недостаточно групп: ожидается {expected_stage_1_groups} групп I этапа"

    group_ids = [group.id for group in groups]
    group_games_played_rows = (
        await db.execute(
            select(GroupGameResult.group_id, func.count(func.distinct(GroupGameResult.game_number)))
            .where(GroupGameResult.group_id.in_(group_ids))
            .group_by(GroupGameResult.group_id)
        )
    ).all()
    games_played_by_group = {int(group_id): int(games_count or 0) for group_id, games_count in group_games_played_rows}

    if any(games_played_by_group.get(group_id, 0) < GROUP_STAGE_GAME_LIMIT for group_id in group_ids):
        return False, "Продвижение возможно только после 3 игр в каждой группе"

    members = list((await db.scalars(select(GroupMember).where(GroupMember.group_id.in_(group_ids)))).all())
    by_group: dict[int, list[GroupMember]] = defaultdict(list)
    for member in members:
        by_group[member.group_id].append(member)

    stage_1_promoted_ids: list[int] = []
    for group in groups:
        ranked = sort_members_for_table(by_group.get(group.id, []))
        per_group_promote_count = max(1, expected_promoted_count // expected_stage_1_groups)
        stage_1_promoted_ids.extend([member.user_id for member in ranked[:per_group_promote_count]])

    if len(stage_1_promoted_ids) != expected_promoted_count:
        return False, f"Недостаточно участников: из I этапа должны пройти ровно {expected_promoted_count} участников"

    direct_invite_users = list(
        (
            await db.scalars(
                select(User)
                .where(User.direct_invite_stage == DIRECT_INVITE_STAGE_2)
                .order_by(User.direct_invite_group_number.asc().nullslast(), User.created_at)
            )
        ).all()
    )
    direct_invite_ids = [user.id for user in direct_invite_users]
    direct_invite_groups = {
        user.id: int(user.direct_invite_group_number)
        for user in direct_invite_users
        if user.direct_invite_group_number is not None
    }

    try:
        stage_2_player_ids = build_stage_2_player_ids(
            stage_1_promoted_ids,
            direct_invite_ids,
            promoted_target_count=expected_promoted_count,
            stage_2_size=stage_2_size,
            direct_invite_groups=direct_invite_groups,
        )
    except ValueError as exc:
        return False, str(exc)

    await rebuild_playoff_stages(db, stage_2_player_ids, stage_2_size=stage_2_size)
    return True, "Playoff-этапы сформированы"


async def get_playoff_stages_with_data(db: AsyncSession) -> list[PlayoffStage]:
    statement = (
        select(PlayoffStage)
        .options(
            selectinload(PlayoffStage.matches),
            selectinload(PlayoffStage.participants),
        )
        .order_by(PlayoffStage.stage_order)
        .execution_options(populate_existing=True)
    )
    stages = list(
        (
            await db.scalars(
                statement
            )
        ).all()
    )
    for stage in stages:
        stage.matches.sort(key=lambda match: (match.group_number, match.game_number))
    return stages


async def start_playoff_stage(db: AsyncSession, stage_id: int) -> None:
    stage = await db.scalar(select(PlayoffStage).where(PlayoffStage.id == stage_id))
    if not stage:
        raise ValueError("Stage not found")
    stage.is_started = True
    await db.commit()


async def move_user_to_stage(db: AsyncSession, from_stage_id: int, to_stage_id: int, user_id: int) -> None:
    participant = await db.scalar(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == from_stage_id, PlayoffParticipant.user_id == user_id))
    if not participant:
        raise ValueError("Участник не найден в исходном этапе")
    target_stage = await db.scalar(select(PlayoffStage).where(PlayoffStage.id == to_stage_id))
    if not target_stage:
        raise ValueError("Целевой этап не найден")

    exists_in_target = await db.scalar(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == to_stage_id, PlayoffParticipant.user_id == user_id))
    if exists_in_target:
        raise ValueError("Игрок уже есть в целевом этапе")

    stage_participants = list(
        (await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == to_stage_id))).all()
    )
    if len(stage_participants) >= target_stage.stage_size:
        raise ValueError("Вместимость целевого этапа превышена")

    next_seed = max((stage_participant.seed for stage_participant in stage_participants), default=0) + 1

    await db.delete(participant)
    db.add(PlayoffParticipant(stage_id=to_stage_id, user_id=user_id, seed=next_seed))
    await db.commit()


async def promote_group_member_to_stage(db: AsyncSession, group_id: int, user_id: int, target_stage_id: int) -> None:
    group_member = await db.scalar(
        select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
    )
    if not group_member:
        raise ValueError("Игрок не найден в указанной группе")

    target_stage = await db.scalar(select(PlayoffStage).where(PlayoffStage.id == target_stage_id))
    if not target_stage:
        raise ValueError("Целевой этап не найден")

    existing_participant = await db.scalar(
        select(PlayoffParticipant).where(
            PlayoffParticipant.stage_id == target_stage_id,
            PlayoffParticipant.user_id == user_id,
        )
    )
    if existing_participant:
        raise ValueError("Игрок уже есть в целевом этапе")

    stage_participants = list(
        (await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == target_stage_id))).all()
    )
    if len(stage_participants) >= target_stage.stage_size:
        raise ValueError("Вместимость целевого этапа превышена")

    next_seed = max((participant.seed for participant in stage_participants), default=0) + 1
    db.add(
        PlayoffParticipant(
            stage_id=target_stage_id,
            user_id=user_id,
            seed=next_seed,
        )
    )
    await db.commit()


async def replace_stage_player(db: AsyncSession, stage_id: int, from_user_id: int, to_user_id: int) -> None:
    participant = await db.scalar(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_id, PlayoffParticipant.user_id == from_user_id))
    if not participant:
        raise ValueError("Игрок для замены не найден")
    exists = await db.scalar(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_id, PlayoffParticipant.user_id == to_user_id))
    if exists:
        raise ValueError("Новый игрок уже присутствует на этапе")
    participant.user_id = to_user_id
    await db.commit()


async def adjust_stage_points(db: AsyncSession, stage_id: int, user_id: int, points_delta: int) -> None:
    participant = await db.scalar(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_id, PlayoffParticipant.user_id == user_id))
    if not participant:
        raise ValueError("Участник этапа не найден")
    participant.points += points_delta
    await db.commit()


async def apply_playoff_match_results(
    db: AsyncSession,
    stage_id: int,
    ordered_user_ids: list[int],
    group_number: int = 1,
) -> None:
    """Применяет результат одной игры внутри группы плей-офф и фиксирует изменения в БД.

    Функция валидирует входные данные (ровно 8 уникальных игроков нужной группы этапа),
    начисляет очки участникам, увеличивает ``match.game_number`` и обновляет ``match.state``.
    Транзакция завершается внутри функции через ``db.commit()``.
    """
    stage = await db.scalar(select(PlayoffStage).where(PlayoffStage.id == stage_id))
    if not stage:
        raise ValueError("Stage not found")
    if len(ordered_user_ids) != 8 or len(set(ordered_user_ids)) != 8:
        raise ValueError("Нужно передать 8 уникальных участников")

    participants = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_id))).all())
    by_user = {p.user_id: p for p in participants}
    expected_group = {p.user_id for p in participants if get_stage_group_number_by_seed(p.seed) == group_number}
    for uid in ordered_user_ids:
        if uid not in by_user:
            raise ValueError("В результатах есть игрок вне этапа")
        if uid not in expected_group:
            raise ValueError("В результатах есть игрок из другой группы этапа")

    match = await db.scalar(
        select(PlayoffMatch).where(PlayoffMatch.stage_id == stage_id, PlayoffMatch.group_number == group_number)
    )
    if not match:
        raise ValueError("Матч/группа для этапа не найдена")
    if match.state == "finished":
        raise ValueError("Матч уже завершен")

    if is_limited_stage(stage.key) and match.game_number > GROUP_STAGE_GAME_LIMIT:
        raise ValueError(
            f"Для этапа {stage.title} достигнут лимит в {GROUP_STAGE_GAME_LIMIT} игры для группы {group_number}"
        )

    for place, user_id in enumerate(ordered_user_ids, start=1):
        apply_points_to_playoff_participant(by_user[user_id], place, stage.scoring_mode)

    match.game_number += 1
    should_finish_limited_stage = is_limited_stage(stage.key) and match.game_number > GROUP_STAGE_GAME_LIMIT

    if should_finish_limited_stage:
        match.state = "finished"
    else:
        match.state = "in_progress"

    await db.commit()


async def finalize_limited_playoff_stage_if_ready(db: AsyncSession, stage_id: int) -> bool:
    """Завершает лимитированную стадию и запускает следующую, если все группы доиграны.

    Raises:
        ValueError: с кодом причины (``stage_groups_missing``, ``group_games_not_completed``,
        ``next_stage_missing``, ``promoted_size_mismatch``, ``next_stage_policy_invalid``),
        если автозавершение невозможно.

    Повторный вызов безопасен: если стадия уже завершена и следующая запущена,
    функция завершится без ошибок и без повторного продвижения.
    """
    stage = await db.scalar(select(PlayoffStage).where(PlayoffStage.id == stage_id))
    if not stage or not is_limited_stage(stage.key):
        return False

    participants = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_id))).all())
    matches = list((await db.scalars(select(PlayoffMatch).where(PlayoffMatch.stage_id == stage_id))).all())
    expected_group_count = get_group_count_for_stage(stage.stage_size, stage.key)
    expected_group_numbers = list(range(1, expected_group_count + 1))
    if not expected_group_numbers:
        raise ValueError("stage_groups_missing")

    participant_groups = {get_stage_group_number_by_seed(participant.seed) for participant in participants}
    match_by_group = {match.group_number: match for match in matches}
    for group_number in expected_group_numbers:
        if group_number not in participant_groups or group_number not in match_by_group:
            raise ValueError("stage_groups_missing")

    for group_number in expected_group_numbers:
        games_played = max(match_by_group[group_number].game_number - 1, 0)
        if games_played < GROUP_STAGE_GAME_LIMIT:
            raise ValueError("group_games_not_completed")

    next_stage = await db.scalar(select(PlayoffStage).where(PlayoffStage.stage_order == stage.stage_order + 1))
    if not next_stage:
        raise ValueError("next_stage_missing")

    if stage.key == "stage_1_4":
        normalized_scoring_mode = (next_stage.scoring_mode or "").strip().lower()
        policy_violations: list[str] = []
        if not is_final_stage_key(next_stage.key):
            policy_violations.append(f"invalid_key:{next_stage.key}")
        if next_stage.stage_size != 8:
            policy_violations.append(f"invalid_size:{next_stage.stage_size}")
        if normalized_scoring_mode not in FINAL_STAGE_SCORING_MODES:
            allowed_modes = ",".join(sorted(FINAL_STAGE_SCORING_MODES))
            policy_violations.append(
                f"invalid_mode:{next_stage.scoring_mode}:allowed={allowed_modes}"
            )
        if policy_violations:
            raise ValueError(f"next_stage_policy_invalid:{';'.join(policy_violations)}")

    promote_top_n = get_promote_top_n(stage.key)
    expected_promoted_count = len(expected_group_numbers) * promote_top_n
    if expected_promoted_count != next_stage.stage_size:
        raise ValueError("promoted_size_mismatch")

    all_groups_finished = all(match_by_group[group_number].state == "finished" for group_number in expected_group_numbers)
    if all_groups_finished and next_stage.is_started:
        return False

    for group_number in expected_group_numbers:
        match_by_group[group_number].state = "finished"
    await db.commit()

    await promote_top_between_stages(db, stage.id, promote_top_n)
    await start_playoff_stage(db, next_stage.id)
    return True


async def simulate_three_random_games_for_stage(db: AsyncSession, stage_id: int) -> None:
    """Симулирует по 3 случайные игры для каждой полной группы в лимитированном этапе.

    Preconditions:
    - этап с ``stage_id`` существует и относится к лимитированным стадиям
      (``stage_2``, ``stage_1_4``);
    - в каждой обрабатываемой группе присутствуют ровно 8 участников.

    Postconditions для каждой обработанной группы:
    - вызывается ``apply_playoff_match_results`` ровно 3 раза;
    - после каждого вызова увеличивается ``PlayoffMatch.game_number``;
    - ``PlayoffMatch.state`` переводится в ``in_progress`` или ``finished`` по правилам этапа;
    - участникам начисляются очки в соответствии с ``stage.scoring_mode``.

    Важно: коммит выполняется внутри ``apply_playoff_match_results`` на каждом шаге симуляции.
    Если этап не найден или не является лимитированным, функция завершится без изменений.
    """
    stage = await db.scalar(select(PlayoffStage).where(PlayoffStage.id == stage_id))
    if not stage or not is_limited_stage(stage.key):
        return

    participants = list(
        (await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage.id))).all()
    )
    grouped_participants: dict[int, list[PlayoffParticipant]] = defaultdict(list)
    for participant in participants:
        grouped_participants[get_stage_group_number_by_seed(participant.seed)].append(participant)

    for group_number, group_members in grouped_participants.items():
        if len(group_members) != 8:
            continue

        ordered_user_ids = [participant.user_id for participant in group_members]
        for _ in range(GROUP_STAGE_GAME_LIMIT):
            shuffled_user_ids = ordered_user_ids.copy()
            random.shuffle(shuffled_user_ids)
            await apply_playoff_match_results(
                db,
                stage.id,
                shuffled_user_ids,
                group_number=group_number,
            )



def _serialize_datetime(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


async def snapshot_tournament_archive(
    db: AsyncSession,
    *,
    winner_user_id: int,
    title: str = "Турнир",
    season: str = "",
    source_tournament_version: str = "v2",
    is_public: bool = True,
) -> TournamentArchive:
    winner = await db.scalar(select(User).where(User.id == winner_user_id))
    if not winner:
        raise ValueError("Победитель турнира не найден")

    groups = list(
        (
            await db.scalars(
                select(TournamentGroup)
                .options(selectinload(TournamentGroup.members).selectinload(GroupMember.user))
                .order_by(TournamentGroup.stage, TournamentGroup.name)
            )
        ).all()
    )

    playoff_stages = list(
        (
            await db.scalars(
                select(PlayoffStage)
                .options(
                    selectinload(PlayoffStage.participants).selectinload(PlayoffParticipant.user),
                    selectinload(PlayoffStage.matches),
                )
                .order_by(PlayoffStage.stage_order, PlayoffStage.id)
            )
        ).all()
    )

    group_payload = [
        {
            "id": group.id,
            "stage": group.stage,
            "name": group.name,
            "lobby_password": group.lobby_password,
            "schedule_text": group.schedule_text,
            "scheduled_at": _serialize_datetime(group.scheduled_at),
            "current_game": group.current_game,
            "is_started": group.is_started,
            "draw_mode": group.draw_mode,
            "members": [
                {
                    "user_id": member.user_id,
                    "nickname": member.user.nickname if member.user else f"#{member.user_id}",
                    "seat": member.seat,
                    "total_points": member.total_points,
                    "first_places": member.first_places,
                    "top4_finishes": member.top4_finishes,
                    "top8_finishes": member.top8_finishes,
                    "eighth_places": member.eighth_places,
                    "last_game_place": member.last_game_place,
                }
                for member in sorted(group.members, key=lambda item: (item.seat, item.id))
            ],
        }
        for group in groups
    ]

    bracket_payload = [
        {
            "id": stage.id,
            "key": stage.key,
            "title": stage.title,
            "stage_size": stage.stage_size,
            "stage_order": stage.stage_order,
            "scoring_mode": stage.scoring_mode,
            "stage_code": stage.stage_code,
            "is_started": stage.is_started,
            "final_candidate_user_id": stage.final_candidate_user_id,
            "participants": [
                {
                    "user_id": participant.user_id,
                    "nickname": participant.user.nickname if participant.user else f"#{participant.user_id}",
                    "seed": participant.seed,
                    "points": participant.points,
                    "wins": participant.wins,
                    "top4_finishes": participant.top4_finishes,
                    "top8_finishes": participant.top8_finishes,
                    "eighth_places": participant.eighth_places,
                    "last_place": participant.last_place,
                    "is_eliminated": participant.is_eliminated,
                }
                for participant in sorted(stage.participants, key=lambda item: item.seed)
            ],
            "matches": [
                {
                    "id": match.id,
                    "match_number": match.match_number,
                    "group_number": match.group_number,
                    "game_number": match.game_number,
                    "lobby_password": match.lobby_password,
                    "schedule_text": match.schedule_text,
                    "scheduled_at": _serialize_datetime(match.scheduled_at),
                    "state": match.state,
                    "winner_user_id": match.winner_user_id,
                    "manual_winner_user_id": match.manual_winner_user_id,
                    "manual_override_note": match.manual_override_note,
                }
                for match in sorted(stage.matches, key=lambda item: (item.group_number, item.match_number))
            ],
        }
        for stage in playoff_stages
    ]

    archive = TournamentArchive(
        title=title.strip() or "Турнир",
        season=season.strip(),
        winner_user_id=winner.id,
        winner_nickname=winner.nickname,
        bracket_payload_json=json.dumps(bracket_payload, ensure_ascii=False),
        group_payload_json=json.dumps(group_payload, ensure_ascii=False),
        source_tournament_version=source_tournament_version.strip() or "v2",
        is_public=is_public,
    )
    db.add(archive)
    await db.flush()
    return archive


async def override_playoff_match_winner(db: AsyncSession, stage_id: int, group_number: int, winner_user_id: int, note: str = "") -> None:
    match = await db.scalar(select(PlayoffMatch).where(PlayoffMatch.stage_id == stage_id, PlayoffMatch.group_number == group_number))
    if not match:
        raise ValueError("Матч/группа для этапа не найдена")

    participant = await db.scalar(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_id, PlayoffParticipant.user_id == winner_user_id))
    if not participant:
        raise ValueError("Победитель должен быть участником этапа")

    match.manual_winner_user_id = winner_user_id
    match.winner_user_id = winner_user_id
    match.manual_override_note = note.strip()
    match.state = "finished"
    await db.commit()


async def finalize_tournament_with_winner(db: AsyncSession, winner_user_id: int) -> str:
    winner = await db.scalar(select(User).where(User.id == winner_user_id))
    if not winner:
        raise ValueError("Победитель турнира не найден")

    setting_values = {
        "tournament_finished": "1",
        "tournament_winner_user_id": str(winner.id),
        "tournament_winner_nickname": winner.nickname,
    }
    for key, value in setting_values.items():
        setting = await db.scalar(select(SiteSetting).where(SiteSetting.key == key))
        if not setting:
            setting = SiteSetting(key=key, value=value)
            db.add(setting)
        else:
            setting.value = value

    return winner.nickname


async def reset_tournament_cycle_after_finish(db: AsyncSession) -> None:
    """Полностью очищает данные текущего турнирного цикла и возвращает стартовые настройки."""
    await db.execute(delete(GroupGameResult))
    await db.execute(delete(GroupManualTieBreak))
    await db.execute(delete(GroupMember))
    await db.execute(delete(TournamentGroup))
    await db.execute(delete(PlayoffMatch))
    await db.execute(delete(PlayoffParticipant))
    await db.execute(delete(PlayoffStage))
    await db.execute(delete(User))

    settings_to_reset = {
        "tournament_started": "0",
        "draw_applied": "0",
        "tournament_finished": "0",
        "tournament_winner_user_id": "",
        "tournament_winner_nickname": "",
        "registration_open": "1",
    }
    for key, value in settings_to_reset.items():
        setting = await db.scalar(select(SiteSetting).where(SiteSetting.key == key))
        if not setting:
            setting = SiteSetting(key=key, value=value)
            db.add(setting)
        else:
            setting.value = value

async def promote_top_between_stages(db: AsyncSession, stage_id: int, top_n: int) -> None:
    stage = await db.scalar(select(PlayoffStage).where(PlayoffStage.id == stage_id))
    if not stage:
        raise ValueError("Stage not found")
    next_stage = await db.scalar(select(PlayoffStage).where(PlayoffStage.stage_order == stage.stage_order + 1))
    if not next_stage:
        raise ValueError("Следующий этап не найден")

    participants = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage.id))).all())
    ranked = sorted(participants, key=playoff_sort_key, reverse=True)

    stage_grouped = split_participants_by_group(participants)
    target_size = get_promoted_count_for_stage(stage)
    if target_size == 0:
        raise ValueError("Для этого этапа продвижение не поддерживается")

    allowed_top_n = get_promote_top_n(stage.key)
    if allowed_top_n == 0:
        raise ValueError("Для этого этапа нельзя выбрать количество продвигаемых из группы")
    if top_n != allowed_top_n:
        raise ValueError(f"Для этапа {stage.title} можно продвинуть только top-{allowed_top_n} из группы")

    def _select_top_with_random_tie(group_ranked: list[PlayoffParticipant], limit: int) -> list[PlayoffParticipant]:
        if len(group_ranked) <= limit:
            return list(group_ranked)

        selected = list(group_ranked[:limit])
        cutoff = selected[-1]
        tie_tail: list[PlayoffParticipant] = []
        boundary_idx = limit - 1
        cutoff_tie_key = playoff_tie_key(cutoff)
        while boundary_idx >= 0 and playoff_tie_key(selected[boundary_idx]) == cutoff_tie_key:
            tie_tail.append(selected[boundary_idx])
            boundary_idx -= 1
        tie_tail.reverse()

        tie_candidates: list[PlayoffParticipant] = []
        scan_idx = limit
        while scan_idx < len(group_ranked) and playoff_tie_key(group_ranked[scan_idx]) == cutoff_tie_key:
            tie_candidates.append(group_ranked[scan_idx])
            scan_idx += 1

        if not tie_candidates:
            return selected

        keep_before_tie = selected[: boundary_idx + 1]
        tie_pool = [*tie_tail, *tie_candidates]
        random.shuffle(tie_pool)
        tie_slots = limit - len(keep_before_tie)
        return [*keep_before_tie, *tie_pool[:tie_slots]]

    top_players: list[PlayoffParticipant] = []
    for group_number in sorted(stage_grouped.keys()):
        group_ranked = sorted(stage_grouped[group_number], key=playoff_sort_key, reverse=True)
        top_players.extend(_select_top_with_random_tie(group_ranked, top_n))

    if len(top_players) < target_size:
        selected_ids = {participant.user_id for participant in top_players}
        for participant in ranked:
            if participant.user_id not in selected_ids:
                top_players.append(participant)
                selected_ids.add(participant.user_id)
            if len(top_players) >= target_size:
                break
    else:
        top_players = sorted(top_players, key=playoff_sort_key, reverse=True)[:target_size]

    await db.execute(delete(PlayoffParticipant).where(PlayoffParticipant.stage_id == next_stage.id))
    seed = 1
    for participant in top_players:
        db.add(
            PlayoffParticipant(
                stage_id=next_stage.id,
                user_id=participant.user_id,
                seed=seed,
                points=0,
                wins=0,
                top4_finishes=0,
                top8_finishes=0,
                last_place=8,
                is_eliminated=False,
            )
        )
        participant.is_eliminated = False
        seed += 1
    promoted_ids = {participant.user_id for participant in top_players}
    for participant in ranked:
        participant.is_eliminated = participant.user_id not in promoted_ids
    await db.commit()
