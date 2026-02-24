"""Заполняет БД тестовыми данными турнира: 56 основных, 20 резервных и 11 direct invite."""

import asyncio
import os
import random
import string

from sqlalchemy import select

from app.models.user import Basket, User
from app.services.rank import mmr_to_rank

MAIN_ROSTER_BASKETS = [
    Basket.QUEEN.value,
    Basket.KING.value,
    Basket.ROOK.value,
    Basket.BISHOP.value,
    Basket.LOW_RANK.value,
]

RESERVE_ROSTER_BASKETS = [
    Basket.QUEEN_RESERVE.value,
    Basket.KING_RESERVE.value,
    Basket.ROOK_RESERVE.value,
    Basket.BISHOP_RESERVE.value,
    Basket.LOW_RANK_RESERVE.value,
]


def _random_nick(prefix: str) -> str:
    # Генерируем короткий псевдоним участника.
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=6))
    return f"{prefix}_{suffix}"


def _random_steam_id() -> str:
    # Генерируем валидный Steam64 идентификатор.
    return f"7656119{random.randint(10_000_000_000, 99_999_999_999)}"


def _rank_from_mmr(mmr: int) -> str:
    # Возвращаем человекочитаемый ранг по MMR с учетом Queen#. 
    queen_rank = random.randint(1, 200) if mmr >= 3380 else None
    return mmr_to_rank(mmr, queen_rank)


async def main() -> None:
    """Создает 56 основных, 20 резервных и 11 direct invite участников."""
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/dac")
    os.environ.setdefault("ADMIN_KEY", "local_seed_admin_key")

    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        existing_steam_ids = set((await db.execute(select(User.steam_id))).scalars().all())

        def next_unique_steam_id() -> str:
            while True:
                steam_id = _random_steam_id()
                if steam_id in existing_steam_ids:
                    continue
                existing_steam_ids.add(steam_id)
                return steam_id

        main_created = 0
        while main_created < 56:
            steam_id = next_unique_steam_id()

            highest_mmr = random.randint(800, 4600)
            current_mmr = random.randint(600, highest_mmr)
            highest_rank = _rank_from_mmr(highest_mmr)
            current_rank = _rank_from_mmr(current_mmr)
            basket = random.choice(MAIN_ROSTER_BASKETS)

            player_index = main_created + 1
            user = User(
                nickname=_random_nick(f"Player{player_index}"),
                steam_input=steam_id,
                steam_id=steam_id,
                game_nickname=_random_nick("GameNick"),
                current_rank=current_rank,
                highest_rank=highest_rank,
                telegram=f"@test_{player_index}",
                discord=f"test_{player_index}",
                basket=basket,
            )
            db.add(user)

            main_created += 1

        reserve_created = 0
        while reserve_created < 20:
            steam_id = next_unique_steam_id()

            highest_mmr = random.randint(800, 4600)
            current_mmr = random.randint(600, highest_mmr)
            highest_rank = _rank_from_mmr(highest_mmr)
            current_rank = _rank_from_mmr(current_mmr)
            basket = random.choice(RESERVE_ROSTER_BASKETS)

            reserve_index = reserve_created + 1
            user = User(
                nickname=_random_nick(f"Reserve{reserve_index}"),
                steam_input=steam_id,
                steam_id=steam_id,
                game_nickname=_random_nick("ReserveNick"),
                current_rank=current_rank,
                highest_rank=highest_rank,
                telegram=f"@reserve_{reserve_index}",
                discord=f"reserve_{reserve_index}",
                basket=basket,
            )
            db.add(user)

            reserve_created += 1

        direct_invites_created = 0
        while direct_invites_created < 11:
            steam_id = next_unique_steam_id()

            highest_mmr = random.randint(800, 4600)
            current_mmr = random.randint(600, highest_mmr)
            highest_rank = _rank_from_mmr(highest_mmr)
            current_rank = _rank_from_mmr(current_mmr)

            invite_index = direct_invites_created + 1
            user = User(
                nickname=_random_nick(f"DirectInvite{invite_index}"),
                steam_input=steam_id,
                steam_id=steam_id,
                game_nickname=_random_nick("InviteNick"),
                current_rank=current_rank,
                highest_rank=highest_rank,
                telegram=f"@direct_invite_{invite_index}",
                discord=f"direct_invite_{invite_index}",
                basket="invited",
                direct_invite_stage="stage_2",
            )
            db.add(user)
            direct_invites_created += 1

        await db.commit()

    print(
        "Сидер завершен: "
        f"основных участников создано {main_created}, "
        f"резервных участников создано {reserve_created}, "
        f"direct invites создано {direct_invites_created}."
    )


if __name__ == "__main__":
    # Запускаем асинхронный сидер из CLI.
    asyncio.run(main())
