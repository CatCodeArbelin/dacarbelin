import asyncio
import random
import string

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.user import User
from app.services.basket_allocator import allocate_basket
from app.services.rank import mmr_to_rank, pick_basket


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
    """Создает 64 тестовых участника с рандомными никами, рангами и корзинами."""
    async with SessionLocal() as db:
        basket_counts_rows = (
            await db.execute(
                select(User.basket, func.count(User.id)).where(User.basket.isnot(None)).group_by(User.basket)
            )
        ).all()
        basket_counts = {name: count for name, count in basket_counts_rows}

        created = 0
        while created < 64:
            steam_id = _random_steam_id()
            exists = await db.scalar(select(User.id).where(User.steam_id == steam_id))
            if exists:
                continue

            highest_mmr = random.randint(800, 4600)
            current_mmr = random.randint(600, highest_mmr)
            highest_rank = _rank_from_mmr(highest_mmr)
            current_rank = _rank_from_mmr(current_mmr)
            target_basket = pick_basket(highest_rank, current_rank)
            basket = allocate_basket(target_basket=target_basket, basket_counts=basket_counts)
            basket_counts[basket] = basket_counts.get(basket, 0) + 1

            player_index = created + 1
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
            created += 1

        await db.commit()

    print("Создано 64 тестовых участника.")


if __name__ == "__main__":
    # Запускаем асинхронный сидер из CLI.
    asyncio.run(main())
