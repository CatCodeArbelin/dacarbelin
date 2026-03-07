"""Проверяет сценарии прямых инвайтов участников между стадиями турнира."""

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


def test_participants_direct_invites_shows_stage_2_user() -> None:
    stage_2_user = User(
        nickname="stage2_user",
        steam_input="stage2_input",
        steam_id="steam_stage2",
        game_nickname="stage2_game",
        current_rank="Pawn-1",
        highest_rank="Knight-1",
        basket=Basket.QUEEN_RESERVE.value,
        direct_invite_stage="stage_2",
    )
    fake_db = _FakeDB(users=[stage_2_user])

    response = asyncio.run(web.participants(request=_fake_request(), basket=Basket.QUEEN.value, view="direct_invites", db=fake_db))

    assert response.status_code == 200
    assert fake_db.last_statement is not None
    compiled = str(fake_db.last_statement)
    assert "WHERE users.basket" not in compiled
    assert "users.direct_invite_stage" in compiled


def test_participants_direct_invites_excludes_non_stage_2_invites() -> None:
    stage_2_user = User(
        nickname="visible_invite",
        steam_input="stage2_input_visible",
        steam_id="steam_stage2_visible",
        game_nickname="stage2_game_visible",
        current_rank="Pawn-1",
        highest_rank="Knight-1",
        basket=Basket.QUEEN.value,
        direct_invite_stage="stage_2",
    )
    fake_db = _FakeDB(users=[stage_2_user])

    response = asyncio.run(web.participants(request=_fake_request(), basket=Basket.QUEEN.value, view="direct_invites", db=fake_db))

    assert response.status_code == 200
    compiled = str(fake_db.last_statement)
    assert "WHERE users.direct_invite_stage" in compiled
    assert "WHERE users.basket" not in compiled
