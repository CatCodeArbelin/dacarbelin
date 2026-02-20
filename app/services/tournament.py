import random
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

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

POINTS_BY_PLACE = {1: 8, 2: 7, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1}
PRIMARY_BASKETS = [
    Basket.QUEEN_TOP.value,
    Basket.QUEEN.value,
    Basket.KING.value,
    Basket.ROOK.value,
    Basket.BISHOP.value,
    Basket.LOW_RANK.value,
]


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
    """Создает автоматическую жеребьевку по 8 игроков на группу для стартового этапа."""
    users = list(
        (
            await db.scalars(
                select(User)
                .where(User.basket.in_(PRIMARY_BASKETS))
                .order_by(User.created_at)
            )
        ).all()
    )
    if len(users) < 64:
        return False, "ДОСТУПНА ТОЛЬКО РУЧНАЯ Жеребьевка, т.к. количество участников в основных корзинах меньше 64"

    await clear_group_stage(db)
    by_basket: dict[str, list[User]] = defaultdict(list)
    for user in users:
        by_basket[user.basket].append(user)

    for bucket in by_basket.values():
        random.shuffle(bucket)

    group_count = min(len(users) // 8, 8)
    groups: list[TournamentGroup] = []
    for idx in range(group_count):
        group = TournamentGroup(name=f"Group {chr(65 + idx)}", lobby_password=generate_password())
        db.add(group)
        groups.append(group)
    await db.flush()

    for idx, group in enumerate(groups):
        picked: list[User] = []
        for basket in [Basket.QUEEN.value, Basket.KING.value, Basket.ROOK.value, Basket.BISHOP.value]:
            if by_basket[basket]:
                picked.append(by_basket[basket].pop())
            if by_basket[basket]:
                picked.append(by_basket[basket].pop())
            if len(picked) >= 8:
                break

        fallback_pool: list[User] = []
        for basket in PRIMARY_BASKETS:
            fallback_pool.extend(by_basket[basket])
        random.shuffle(fallback_pool)
        while len(picked) < 8 and fallback_pool:
            candidate = fallback_pool.pop()
            if candidate not in picked and candidate in by_basket[candidate.basket]:
                by_basket[candidate.basket].remove(candidate)
                picked.append(candidate)

        for seat, player in enumerate(picked, start=1):
            db.add(GroupMember(group_id=group.id, user_id=player.id, seat=seat))

    await db.commit()
    return True, "Автоматическая жеребьевка успешно создана"


def sort_members_for_table(
    members: list[GroupMember],
    manual_tie_break_priorities: dict[int, int] | None = None,
) -> list[GroupMember]:
    # Сортируем таблицу по очкам и tie-break правилам. Финальный ключ — user_id для стабильности.
    manual_tie_break_priorities = manual_tie_break_priorities or {}
    return sorted(
        members,
        key=lambda m: (
            m.total_points,
            m.first_places,
            m.top4_finishes,
            -m.eighth_places,
            -m.last_game_place,
            manual_tie_break_priorities.get(m.user_id, -1),
            -m.user_id,
        ),
        reverse=True,
    )


async def apply_manual_tie_break(db: AsyncSession, group_id: int, ordered_user_ids: list[int]) -> None:
    # Фиксируем ручной тай-брейк только для игроков с полностью равными метриками.
    if len(ordered_user_ids) < 2 or len(ordered_user_ids) != len(set(ordered_user_ids)):
        raise ValueError("Нужно передать минимум 2 уникальных user_id")

    members = list((await db.scalars(select(GroupMember).where(GroupMember.group_id == group_id))).all())
    members_by_user = {member.user_id: member for member in members}
    if not members:
        raise ValueError("Group not found")

    for user_id in ordered_user_ids:
        if user_id not in members_by_user:
            raise ValueError("В тай-брейке есть игрок, которого нет в группе")

    metric_key = lambda m: (m.total_points, m.first_places, m.top4_finishes, m.eighth_places, m.last_game_place)
    first_metrics = metric_key(members_by_user[ordered_user_ids[0]])
    for user_id in ordered_user_ids[1:]:
        if metric_key(members_by_user[user_id]) != first_metrics:
            raise ValueError("Ручной тай-брейк разрешен только для полностью равных игроков")

    await db.execute(delete(GroupManualTieBreak).where(GroupManualTieBreak.group_id == group_id))
    for priority, user_id in enumerate(reversed(ordered_user_ids), start=1):
        db.add(GroupManualTieBreak(group_id=group_id, user_id=user_id, priority=priority))

    await db.commit()


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
        member.eighth_places += 1 if place == 8 else 0
        member.last_game_place = place

    if group.current_game < 3:
        group.current_game += 1
    await db.commit()


PLAYOFF_STAGE_SIZES = [64, 32, 16, 8]
FINAL_SCORING_MODE = "final_22_top1"


def playoff_sort_key(participant: PlayoffParticipant) -> tuple[int, int, int, int, int]:
    return (
        participant.points,
        participant.wins,
        participant.top4_finishes,
        -participant.last_place,
        -participant.user_id,
    )


def apply_points_to_playoff_participant(participant: PlayoffParticipant, place: int, scoring_mode: str) -> None:
    if scoring_mode == FINAL_SCORING_MODE:
        participant.points += 8 if place == 1 else 1
    else:
        participant.points += POINTS_BY_PLACE[place]
    if place == 1:
        participant.wins += 1
    if place <= 4:
        participant.top4_finishes += 1
    participant.last_place = place


async def rebuild_playoff_stages(db: AsyncSession, player_ids: list[int]) -> list[PlayoffStage]:
    usable_count = len(player_ids)
    stages_to_create = [size for size in PLAYOFF_STAGE_SIZES if usable_count >= size]
    if not stages_to_create:
        raise ValueError("Недостаточно игроков для playoff-этапов")

    await db.execute(delete(PlayoffMatch))
    await db.execute(delete(PlayoffParticipant))
    await db.execute(delete(PlayoffStage))

    stages: list[PlayoffStage] = []
    for order, size in enumerate(stages_to_create):
        stage = PlayoffStage(
            key=f"top_{size}",
            title=f"Top {size}",
            stage_size=size,
            stage_order=order,
            scoring_mode=FINAL_SCORING_MODE if size == 8 else "standard",
            is_started=False,
        )
        db.add(stage)
        stages.append(stage)
    await db.flush()

    first_stage = stages[0]
    seeded = player_ids[: first_stage.stage_size]
    for seed, user_id in enumerate(seeded, start=1):
        db.add(PlayoffParticipant(stage_id=first_stage.id, user_id=user_id, seed=seed))

    for stage in stages:
        for match_number in range(1, stage.stage_size // 8 + 1):
            db.add(PlayoffMatch(stage_id=stage.id, match_number=match_number, lobby_password=generate_password()))

    await db.commit()
    return stages


async def generate_playoff_from_groups(db: AsyncSession) -> tuple[bool, str]:
    groups = list((await db.scalars(select(TournamentGroup).where(TournamentGroup.stage == "group_stage"))).all())
    if not groups:
        return False, "Сначала требуется сформировать групповой этап"

    members = list((await db.scalars(select(GroupMember).where(GroupMember.group_id.in_([g.id for g in groups])))).all())
    by_group: dict[int, list[GroupMember]] = defaultdict(list)
    for member in members:
        by_group[member.group_id].append(member)

    promoted: list[int] = []
    for group in groups:
        ranked = sort_members_for_table(by_group.get(group.id, []))
        promoted.extend([m.user_id for m in ranked[:8]])

    if len(promoted) < 8:
        return False, "Недостаточно участников для playoff"

    await rebuild_playoff_stages(db, promoted)
    return True, "Playoff-этапы сформированы"


async def get_playoff_stages_with_data(db: AsyncSession) -> list[PlayoffStage]:
    stages = list((await db.scalars(select(PlayoffStage).order_by(PlayoffStage.stage_order))).all())
    for stage in stages:
        stage.matches = list((await db.scalars(select(PlayoffMatch).where(PlayoffMatch.stage_id == stage.id).order_by(PlayoffMatch.match_number))).all())
        stage.participants = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage.id))).all())
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
    exists_in_target = await db.scalar(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == to_stage_id, PlayoffParticipant.user_id == user_id))
    if exists_in_target:
        raise ValueError("Игрок уже есть в целевом этапе")
    participant.is_eliminated = True
    db.add(PlayoffParticipant(stage_id=to_stage_id, user_id=user_id, seed=participant.seed))
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


async def apply_playoff_match_results(db: AsyncSession, stage_id: int, ordered_user_ids: list[int]) -> None:
    stage = await db.scalar(select(PlayoffStage).where(PlayoffStage.id == stage_id))
    if not stage:
        raise ValueError("Stage not found")
    if len(ordered_user_ids) != 8 or len(set(ordered_user_ids)) != 8:
        raise ValueError("Нужно передать 8 уникальных участников")

    participants = list((await db.scalars(select(PlayoffParticipant).where(PlayoffParticipant.stage_id == stage_id))).all())
    by_user = {p.user_id: p for p in participants}
    for uid in ordered_user_ids:
        if uid not in by_user:
            raise ValueError("В результатах есть игрок вне этапа")

    for place, user_id in enumerate(ordered_user_ids, start=1):
        apply_points_to_playoff_participant(by_user[user_id], place, stage.scoring_mode)

    if stage.scoring_mode == FINAL_SCORING_MODE:
        winner = max(participants, key=playoff_sort_key)
        if winner.points >= 22:
            top_points = sorted([p.points for p in participants], reverse=True)
            if len(top_points) == 1 or top_points[0] > top_points[1]:
                for match in (await db.scalars(select(PlayoffMatch).where(PlayoffMatch.stage_id == stage_id))).all():
                    match.state = "finished"
                    match.winner_user_id = winner.user_id

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
    top_players = ranked[:top_n]

    await db.execute(delete(PlayoffParticipant).where(PlayoffParticipant.stage_id == next_stage.id))
    for seed, participant in enumerate(top_players, start=1):
        db.add(PlayoffParticipant(stage_id=next_stage.id, user_id=participant.user_id, seed=seed))
        participant.is_eliminated = False
    for participant in ranked[top_n:]:
        participant.is_eliminated = True
    await db.commit()
