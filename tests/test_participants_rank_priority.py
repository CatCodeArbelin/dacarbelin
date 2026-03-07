"""Проверяет сортировку участников на странице participants по приоритету ранга."""

import asyncio
from types import SimpleNamespace

from app.models.user import Basket, User
from app.routers import web


class _FakeScalarResult:
    def __init__(self, users: list[User]) -> None:
        self._users = users

    def all(self) -> list[User]:
        return self._users


class _FakeDB:
    def __init__(self, users: list[User]) -> None:
        self.users = users
        self.last_statement = None

    async def scalars(self, statement):
        self.last_statement = statement
        return _FakeScalarResult(self.users)


def _fake_request():
    return SimpleNamespace(cookies={}, query_params={})


def test_participants_baskets_mode_queries_all_users_without_basket_filter() -> None:
    users = [
        User(
            nickname="queen_user",
            steam_input="queen_input",
            steam_id="steam_queen",
            game_nickname="queen_game",
            current_rank="Pawn-1",
            highest_rank="Knight-1",
            basket=Basket.QUEEN.value,
        )
    ]
    fake_db = _FakeDB(users=users)

    response = asyncio.run(web.participants(request=_fake_request(), view="baskets", db=fake_db))

    assert response.status_code == 200
    assert fake_db.last_statement is not None
    compiled = str(fake_db.last_statement)
    assert "FROM users" in compiled
    assert "WHERE users.basket" not in compiled
    assert "ORDER BY CASE" in compiled


def test_participants_rank_priority_queen_places_queen_pair_first_in_order_by() -> None:
    fake_db = _FakeDB(users=[])

    asyncio.run(web.participants(request=_fake_request(), view="baskets", rank_priority=Basket.QUEEN.value, db=fake_db))

    compiled = str(fake_db.last_statement)
    queen_idx = compiled.find("users.basket = :basket_1")
    queen_reserve_idx = compiled.find("users.basket = :basket_2")
    king_idx = compiled.find("users.basket = :basket_3")
    assert queen_idx >= 0 and queen_reserve_idx > queen_idx and king_idx > queen_reserve_idx


def test_participants_rank_priority_other_ranks_place_corresponding_pair_first() -> None:
    fake_db = _FakeDB(users=[])
    cases = [
        (Basket.KING.value, ":basket_1", ":basket_2", ":basket_3"),
        (Basket.ROOK.value, ":basket_1", ":basket_2", ":basket_3"),
        (Basket.BISHOP.value, ":basket_1", ":basket_2", ":basket_3"),
        (Basket.LOW_RANK.value, ":basket_1", ":basket_2", ":basket_3"),
    ]

    for rank_priority, first_token, second_token, third_token in cases:
        asyncio.run(web.participants(request=_fake_request(), view="baskets", rank_priority=rank_priority, db=fake_db))
        compiled = str(fake_db.last_statement)
        params = fake_db.last_statement.compile().params
        assert compiled.find(f"users.basket = {first_token}") < compiled.find(f"users.basket = {second_token}")
        assert params[first_token.lstrip(":")] in [rank_priority, f"{rank_priority}_reserve"]
        assert params[second_token.lstrip(":")] in [rank_priority, f"{rank_priority}_reserve"]
        assert params[third_token.lstrip(":")] not in [rank_priority, f"{rank_priority}_reserve"]


def test_participants_rank_priority_sorts_selected_tier_first_with_deterministic_queen_order() -> None:
    fake_db = _FakeDB(users=[])

    asyncio.run(web.participants(request=_fake_request(), view="baskets", rank_priority=Basket.QUEEN.value, db=fake_db))

    compiled = str(fake_db.last_statement)
    assert "CAST(substr(users.highest_rank, :substr_1) AS INTEGER)" in compiled
    assert "users.highest_rank LIKE :highest_rank_1" in compiled
    assert "coalesce" in compiled.lower()



def test_participants_invalid_rank_priority_falls_back_to_queen() -> None:
    fake_db = _FakeDB(users=[])

    asyncio.run(web.participants(request=_fake_request(), view="baskets", rank_priority="invalid-rank", db=fake_db))

    params = fake_db.last_statement.compile().params
    assert params["basket_1"] == Basket.QUEEN.value
    assert params["basket_2"] == Basket.QUEEN_RESERVE.value
