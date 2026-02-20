import random
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tournament import GroupGameResult, GroupMember, TournamentGroup
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


async def create_manual_draw(db: AsyncSession, user_ids: list[int]) -> tuple[bool, str]:
    """Создает ручную жеребьевку из списка user_id и раскладывает по группам по 8 участников."""
    if not user_ids:
        return False, "Передайте список user_id для ручной жеребьевки"
    if len(user_ids) % 8 != 0:
        return False, "Количество участников для ручной жеребьевки должно делиться на 8"

    users = list((await db.scalars(select(User).where(User.id.in_(user_ids)))).all())
    if len(users) != len(set(user_ids)):
        return False, "Некоторые user_id не найдены"

    await clear_group_stage(db)
    ordered_users = sorted(users, key=lambda u: user_ids.index(u.id))
    group_count = len(ordered_users) // 8
    for group_index in range(group_count):
        group = TournamentGroup(name=f"Group {chr(65 + group_index)}", lobby_password=generate_password())
        db.add(group)
        await db.flush()
        for seat, player in enumerate(ordered_users[group_index * 8 : group_index * 8 + 8], start=1):
            db.add(GroupMember(group_id=group.id, user_id=player.id, seat=seat))

    await db.commit()
    return True, "Ручная жеребьевка успешно создана"


async def create_auto_draw(db: AsyncSession) -> tuple[bool, str]:
    """Создает автоматическую жеребьевку по 8 игроков на группу для стартового этапа."""
    users = list((await db.scalars(select(User).where(User.basket.in_(PRIMARY_BASKETS)).order_by(User.created_at))).all())
    if len(users) < 64:
        return False, "ДОСТУПНА ТОЛЬКО РУЧНАЯ Жеребьевка, т.к. количество участников в основных корзинах меньше 64"

    await clear_group_stage(db)
    by_basket: dict[str, list[User]] = defaultdict(list)
    for user in users:
        by_basket[user.basket].append(user)
    for bucket in by_basket.values():
        random.shuffle(bucket)

    group_count = min(len(users) // 8, 8)
    for idx in range(group_count):
        group = TournamentGroup(name=f"Group {chr(65 + idx)}", lobby_password=generate_password())
        db.add(group)
        await db.flush()

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


async def move_member_to_group(db: AsyncSession, user_id: int, target_group_id: int) -> tuple[bool, str]:
    # Перемещаем участника в другую группу с ограничением 8 мест.
    target_group_members = list((await db.scalars(select(GroupMember).where(GroupMember.group_id == target_group_id))).all())
    if len(target_group_members) >= 8:
        return False, "В целевой группе уже 8 участников"

    member = await db.scalar(select(GroupMember).where(GroupMember.user_id == user_id))
    if not member:
        return False, "Участник не найден в текущих группах"

    member.group_id = target_group_id
    member.seat = len(target_group_members) + 1
    await db.commit()
    return True, "Участник перемещен"


async def add_member_to_group(db: AsyncSession, user_id: int, group_id: int) -> tuple[bool, str]:
    # Добавляем участника в группу вручную.
    group_members = list((await db.scalars(select(GroupMember).where(GroupMember.group_id == group_id))).all())
    if len(group_members) >= 8:
        return False, "В группе уже 8 участников"
    existing = await db.scalar(select(GroupMember).where(GroupMember.user_id == user_id))
    if existing:
        return False, "Участник уже находится в другой группе"

    db.add(GroupMember(group_id=group_id, user_id=user_id, seat=len(group_members) + 1))
    await db.commit()
    return True, "Участник добавлен в группу"


def sort_members_for_table(members: list[GroupMember]) -> list[GroupMember]:
    # Сортируем таблицу по очкам и tie-break правилам.
    return sorted(
        members,
        key=lambda m: (m.total_points, m.first_places, m.top4_finishes, -m.eighth_places, -m.last_game_place, random.random()),
        reverse=True,
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
    existing = await db.scalar(select(GroupGameResult).where(GroupGameResult.group_id == group_id, GroupGameResult.game_number == game_number))
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
