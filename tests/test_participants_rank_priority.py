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


def test_participants_rank_priority_queen_places_queen_pair_first() -> None:
    fake_db = _FakeDB(users=[])

    asyncio.run(web.participants(request=_fake_request(), view="baskets", rank_priority=Basket.QUEEN.value, db=fake_db))

    params = fake_db.last_statement.compile().params
    assert params["basket_1"] == [Basket.QUEEN.value, Basket.QUEEN_RESERVE.value]


def test_participants_rank_priority_other_ranks_place_corresponding_pair_first() -> None:
    fake_db = _FakeDB(users=[])
    cases = [
        (Basket.KING.value, [Basket.KING.value, Basket.KING_RESERVE.value]),
        (Basket.ROOK.value, [Basket.ROOK.value, Basket.ROOK_RESERVE.value]),
        (Basket.BISHOP.value, [Basket.BISHOP.value, Basket.BISHOP_RESERVE.value]),
        (Basket.LOW_RANK.value, [Basket.LOW_RANK.value, Basket.LOW_RANK_RESERVE.value]),
    ]

    for rank_priority, expected_pair in cases:
        asyncio.run(web.participants(request=_fake_request(), view="baskets", rank_priority=rank_priority, db=fake_db))
        params = fake_db.last_statement.compile().params
        assert params["basket_1"] == expected_pair
