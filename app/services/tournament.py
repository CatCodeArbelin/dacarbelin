"""Реализует основную бизнес-логику управления турниром и сеткой матчей."""

from collections import defaultdict
import random

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tournament import (
    GroupGameResult,
    GroupMember,
    PlayoffMatch,
    PlayoffParticipant,
    PlayoffStage,
    TournamentGroup,
)
from app.models.user import Basket, User

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
    """Создает автоматическую жеребьевку в формате 7x8 для стартового этапа."""
    users = list(
        (
            await db.scalars(
                select(User)
                .where(User.basket.in_(PRIMARY_BASKETS))
                .order_by(User.created_at)
            )
        ).all()
    )
    if len(users) < 56:
        return False, "Автожеребьевка недоступна: требуется минимум 56 валидных участников (формат 7x8). Доступна только ручная жеребьевка."

    expected_group_count = 7

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
                if len(picked) >= 8:
                    break

            fallback_pool: list[User] = []
            for basket in PRIMARY_BASKETS:
                if basket == Basket.INVITED.value:
                    continue
                fallback_pool.extend(by_basket[basket])
            random.shuffle(fallback_pool)
            while len(picked) < 8 and fallback_pool:
                candidate = fallback_pool.pop()
                if candidate not in picked and candidate in by_basket[candidate.basket]:
                    by_basket[candidate.basket].remove(candidate)
                    picked.append(candidate)

            unique_ids = {player.id for player in picked}
            if len(picked) != 8 or len(unique_ids) != 8:
                raise ValueError(
                    "Не удалось собрать 8 уникальных участников для группы в формате 7x8. Доступна только ручная жеребьевка."
                )

            assigned_by_group.append(picked)

        assigned_players_count = sum(len(group_players) for group_players in assigned_by_group)
        if len(assigned_by_group) != 7 or assigned_players_count != 56:
            raise ValueError(
                "Итоговая автожеребьевка невалидна: требуется ровно 7 групп и 56 назначенных участников (7x8). "
                "Доступна только ручная жеребьевка."
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


async def create_manual_draw(db: AsyncSession, group_count: int, user_ids: list[int]) -> None:
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

    for offset, user_id in enumerate(user_ids):
        group = groups[offset % group_count]
        await validate_group_member_constraints(db, group_id=group.id, user_id=user_id)
        seat = 1 + len(list((await db.scalars(select(GroupMember.id).where(GroupMember.group_id == group.id))).all()))
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
    ("stage_1_8", "Stage 1/8", 32, "standard"),
    ("stage_1_4", "Stage 1/4", 16, "standard"),
    ("stage_final", "Final", 8, "final_22_top1"),
]
FINAL_SCORING_MODE = "final_22_top1"
GROUP_STAGE_GAME_LIMIT = 3
LIMITED_PLAYOFF_STAGE_KEYS = {"stage_1_8", "stage_1_4"}
DIRECT_INVITE_STAGE_2 = "stage_2"
STAGE_2_DIRECT_INVITES_LIMIT = 11


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


def apply_points_to_playoff_participant(participant: PlayoffParticipant, place: int, scoring_mode: str) -> None:
    participant.points += POINTS_BY_PLACE[place]
    if place == 1:
        participant.wins += 1
    if place <= 4:
        participant.top4_finishes += 1
    participant.top8_finishes = (participant.top8_finishes or 0) + 1
    participant.last_place = place


def get_group_count_for_stage(stage_size: int) -> int:
    return max(1, stage_size // 8)


def get_promoted_count_for_stage(stage: PlayoffStage) -> int:
    if stage.key == "stage_1_8":
        return 16
    if stage.key == "stage_1_4":
        return 8
    return 0


def get_stage_group_number_by_seed(seed: int) -> int:
    return ((seed - 1) // 8) + 1


def get_stage_group_label(stage_key: str, group_number: int) -> str:
    if stage_key in {"stage_1_8", "stage_1_4", "stage_semifinal_groups"}:
        return chr(ord("A") + max(group_number - 1, 0))
    if stage_key == "stage_final":
        return "Final"
    return str(group_number)


def build_stage_2_player_ids(stage_1_promoted_ids: list[int], direct_invite_ids: list[int]) -> list[int]:
    if len(stage_1_promoted_ids) != 21:
        raise ValueError("Во II этап должны проходить ровно 21 участник из I этапа")
    if len(direct_invite_ids) > STAGE_2_DIRECT_INVITES_LIMIT:
        raise ValueError("Нельзя превысить 11 прямых инвайтов во II этап")

    required_invites = 32 - len(stage_1_promoted_ids)
    if len(direct_invite_ids) < required_invites:
        raise ValueError(f"Для II этапа требуется минимум {required_invites} прямых инвайтов")

    direct_invite_ids = direct_invite_ids[:required_invites]

    promoted_set = set(stage_1_promoted_ids)
    direct_set = set(direct_invite_ids)
    if len(promoted_set) != len(stage_1_promoted_ids) or len(direct_set) != len(direct_invite_ids):
        raise ValueError("В списках участников обнаружены дубликаты")
    if promoted_set.intersection(direct_set):
        raise ValueError("Игрок не может быть одновременно прошедшим и прямым инвайтом")

    stage_2_player_ids = [*stage_1_promoted_ids, *direct_invite_ids]
    if len(stage_2_player_ids) != 32:
        raise ValueError("Во II этапе должно быть ровно 32 участника")
    return stage_2_player_ids


def build_stage_2_direct_invite_preview(
    direct_invite_ids: list[int],
    *,
    promoted_count: int = 21,
) -> list[dict[str, int]]:
    """Строит preview по прямым инвайтам во II этап с теми же seed, что и при генерации этапа."""
    required_invites = max(0, 32 - promoted_count)
    seed_start = promoted_count + 1
    preview: list[dict[str, int]] = []
    for index, user_id in enumerate(direct_invite_ids[:required_invites]):
        seed = seed_start + index
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


async def rebuild_playoff_stages(db: AsyncSession, player_ids: list[int]) -> list[PlayoffStage]:
    usable_count = len(player_ids)
    stages_to_create = get_playoff_stage_blueprint(usable_count)
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
            groups_count = get_group_count_for_stage(stage.stage_size)

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
    groups = list((await db.scalars(select(TournamentGroup).where(TournamentGroup.stage == "group_stage"))).all())
    if not groups:
        return False, "Сначала требуется сформировать групповой этап"

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
        stage_1_promoted_ids.extend([member.user_id for member in ranked[:3]])

    if len(stage_1_promoted_ids) != 21:
        return False, "Недостаточно участников: из I этапа должны пройти ровно 21 участник"

    direct_invite_ids = list(
        (
            await db.scalars(
                select(User.id)
                .where(User.direct_invite_stage == DIRECT_INVITE_STAGE_2)
                .order_by(User.created_at)
            )
        ).all()
    )

    try:
        stage_2_player_ids = build_stage_2_player_ids(stage_1_promoted_ids, direct_invite_ids)
    except ValueError as exc:
        return False, str(exc)

    await rebuild_playoff_stages(db, stage_2_player_ids)
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

    participant.is_eliminated = True
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

    if stage.key in LIMITED_PLAYOFF_STAGE_KEYS and match.game_number > GROUP_STAGE_GAME_LIMIT:
        raise ValueError(
            f"Для этапа {stage.title} достигнут лимит в {GROUP_STAGE_GAME_LIMIT} игры для группы {group_number}"
        )

    for place, user_id in enumerate(ordered_user_ids, start=1):
        apply_points_to_playoff_participant(by_user[user_id], place, stage.scoring_mode)

    match.game_number += 1
    should_finish_limited_stage = (
        stage.key in LIMITED_PLAYOFF_STAGE_KEYS and match.game_number > GROUP_STAGE_GAME_LIMIT
    )
    should_finish_final_stage = False

    if stage.scoring_mode == FINAL_SCORING_MODE:
        ranked = sorted(participants, key=playoff_sort_key, reverse=True)
        leader = ranked[0]
        if stage.final_candidate_user_id:
            if ordered_user_ids[0] == stage.final_candidate_user_id:
                match.winner_user_id = stage.final_candidate_user_id
                should_finish_final_stage = True
            elif leader.points >= 22:
                stage.final_candidate_user_id = leader.user_id
        elif leader.points >= 22:
            stage.final_candidate_user_id = leader.user_id

    if should_finish_limited_stage or should_finish_final_stage:
        match.state = "finished"
    else:
        match.state = "in_progress"

    await db.commit()




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

    allowed_top_n_by_stage = {
        "stage_1_8": 4,
        "stage_1_4": 4,
    }
    allowed_top_n = allowed_top_n_by_stage.get(stage.key)
    if allowed_top_n is None:
        raise ValueError("Для этого этапа нельзя выбрать количество продвигаемых из группы")
    if top_n != allowed_top_n:
        raise ValueError(f"Для этапа {stage.title} можно продвинуть только top-{allowed_top_n} из группы")

    top_players: list[PlayoffParticipant] = []
    for group_number in sorted(stage_grouped.keys()):
        group_ranked = sorted(stage_grouped[group_number], key=playoff_sort_key, reverse=True)
        top_players.extend(group_ranked[:top_n])

    if stage.key == "stage_1_8":
        direct_invite_users = list(
            (
                await db.scalars(
                    select(User.id)
                    .where(User.direct_invite_stage == DIRECT_INVITE_STAGE_2)
                    .order_by(User.created_at)
                )
            ).all()
        )
        stage_2_player_ids = build_stage_2_player_ids(
            [participant.user_id for participant in top_players],
            direct_invite_users,
        )
        selected_participants_by_id = {participant.user_id: participant for participant in participants}
        top_players = [selected_participants_by_id[player_id] for player_id in stage_2_player_ids if player_id in selected_participants_by_id]
        invited_ids = [player_id for player_id in stage_2_player_ids if player_id not in selected_participants_by_id]
    elif len(top_players) < target_size:
        selected_ids = {participant.user_id for participant in top_players}
        for participant in ranked:
            if participant.user_id not in selected_ids:
                top_players.append(participant)
                selected_ids.add(participant.user_id)
            if len(top_players) >= target_size:
                break
        invited_ids = []
    else:
        top_players = sorted(top_players, key=playoff_sort_key, reverse=True)[:target_size]
        invited_ids = []

    await db.execute(delete(PlayoffParticipant).where(PlayoffParticipant.stage_id == next_stage.id))
    seed = 1
    for participant in top_players:
        db.add(PlayoffParticipant(stage_id=next_stage.id, user_id=participant.user_id, seed=seed))
        participant.is_eliminated = False
        seed += 1
    if stage.key == "stage_1_8":
        for invited_id in invited_ids:
            db.add(PlayoffParticipant(stage_id=next_stage.id, user_id=invited_id, seed=seed))
            seed += 1
    if stage.key == "stage_1_8":
        promoted_ids = {participant.user_id for participant in top_players}
        for invited_id in invited_ids:
            promoted_ids.add(invited_id)
    else:
        promoted_ids = {participant.user_id for participant in top_players}
    for participant in ranked:
        participant.is_eliminated = participant.user_id not in promoted_ids
    await db.commit()
