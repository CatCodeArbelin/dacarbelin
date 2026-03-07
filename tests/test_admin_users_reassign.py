from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.tournament import PlayoffParticipant, PlayoffStage
from app.models.user import Basket, User
from app.routers import web


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, *, user: User, stage: PlayoffStage, memberships: list[PlayoffParticipant]):
        self.user = user
        self.stage = stage
        self.memberships = memberships
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def get(self, model, key):
        if model is User and key == self.user.id:
            return self.user
        if model is PlayoffStage and key == self.stage.id:
            return self.stage
        return None

    async def scalars(self, statement):
        sql = str(statement)
        if "FROM playoff_participants" in sql and "playoff_participants.user_id" in sql:
            return _ScalarResult(self.memberships)
        if "FROM playoff_participants" in sql and "playoff_participants.stage_id" in sql:
            return _ScalarResult(self.memberships)
        return _ScalarResult([])

    async def scalar(self, statement):
        sql = str(statement)
        if "FROM group_members" in sql:
            return None
        if "FROM playoff_participants" in sql:
            return next((m for m in self.memberships if m.stage_id == self.stage.id and m.user_id == self.user.id), None)
        return None

    def add(self, obj):
        self.memberships.append(obj)


@pytest.mark.asyncio
async def test_admin_reassign_user_moves_player_between_stages(monkeypatch) -> None:
    user = User(id=55, nickname="mover", basket=Basket.QUEEN.value)
    from_membership = PlayoffParticipant(stage_id=10, user_id=55, seed=1)
    target_stage = PlayoffStage(id=20, key="stage_2", title="Stage 2", stage_size=16, stage_order=1)
    db = _FakeDB(user=user, stage=target_stage, memberships=[from_membership])

    async def fake_move_user_to_stage(db, from_stage_id: int, to_stage_id: int, user_id: int):
        db.memberships[:] = [m for m in db.memberships if m.user_id != user_id]
        db.memberships.append(PlayoffParticipant(stage_id=to_stage_id, user_id=user_id, seed=9))

    monkeypatch.setattr(web, "move_user_to_stage", fake_move_user_to_stage)

    response = await web.admin_reassign_user(
        user_id=55,
        target_stage_id=20,
        target_group_number=None,
        replace_from_user_id=None,
        quick_move=None,
        db=db,
    )

    assert response.status_code == 303
    assert "msg_player_moved" in response.headers["location"]
    assert any(member.stage_id == 20 and member.user_id == 55 for member in db.memberships)


@pytest.mark.asyncio
async def test_admin_reassign_user_promotes_reserve_basket_on_move() -> None:
    user = User(id=56, nickname="reserve", basket=Basket.ROOK_RESERVE.value)
    target_stage = PlayoffStage(id=20, key="stage_2", title="Stage 2", stage_size=16, stage_order=1)
    target_membership = PlayoffParticipant(stage_id=20, user_id=56, seed=4)
    db = _FakeDB(user=user, stage=target_stage, memberships=[target_membership])

    response = await web.admin_reassign_user(
        user_id=56,
        target_stage_id=20,
        target_group_number=None,
        replace_from_user_id=None,
        quick_move=None,
        db=db,
    )

    assert response.status_code == 303
    assert "msg_player_moved" in response.headers["location"]
    assert user.basket == Basket.ROOK.value


def test_admin_users_page_fetches_all_users_without_limit(monkeypatch) -> None:
    captured = {}

    class _DB:
        async def scalars(self, statement):
            sql = str(statement)
            if "FROM users" in sql and "ORDER BY users.created_at DESC" in sql:
                captured["users_query"] = sql
                users = [User(id=index, nickname=f"u{index}") for index in range(1, 305)]
                return _ScalarResult(users)
            if "FROM playoff_stages" in sql:
                return _ScalarResult([])
            if "FROM playoff_participants" in sql:
                return _ScalarResult([])
            if "FROM tournament_groups" in sql:
                return _ScalarResult([])
            return _ScalarResult([])

        async def execute(self, statement):
            return SimpleNamespace(all=lambda: [])

    class _Req:
        cookies = {}
        query_params = {}

    async def fake_get_draw_applied(db):
        return False

    async def fake_get_tournament_started(db):
        return False

    monkeypatch.setattr(web, "get_draw_applied", fake_get_draw_applied)
    monkeypatch.setattr(web, "get_tournament_started", fake_get_tournament_started)

    import asyncio

    response = asyncio.run(web.admin_users_page(request=_Req(), db=_DB()))

    assert response.status_code == 200
    assert "users_query" in captured
    assert "LIMIT" not in captured["users_query"].upper()
