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
    def __init__(self, *, user: User, stage: PlayoffStage | None, memberships: list[PlayoffParticipant]):
        self.user = user
        self.stage = stage
        self.memberships = memberships
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.flush = AsyncMock()

    async def get(self, model, key):
        if model is User and key == self.user.id:
            return self.user
        if model is PlayoffStage and self.stage and key == self.stage.id:
            return self.stage
        return None

    async def scalars(self, statement):
        sql = str(statement)
        if "FROM playoff_participants" in sql and "playoff_participants.user_id" in sql:
            return _ScalarResult(self.memberships)
        if "FROM playoff_participants" in sql and "playoff_participants.stage_id" in sql:
            return _ScalarResult(self.memberships)
        if "FROM playoff_stages" in sql:
            return _ScalarResult([self.stage] if self.stage else [])
        return _ScalarResult([])

    async def scalar(self, statement):
        sql = str(statement)
        if "FROM group_members" in sql:
            return None
        if "FROM playoff_stages" in sql and "playoff_stages.key" in sql:
            return self.stage
        if "FROM playoff_participants" in sql:
            if self.stage is None:
                return None
            return next((m for m in self.memberships if m.stage_id == self.stage.id and m.user_id == self.user.id), None)
        return None

    def add(self, obj):
        if isinstance(obj, PlayoffStage):
            if self.stage is None:
                self.stage = obj
                self.stage.id = 999
            return
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
        target_stage_id="20",
        target_group_number=None,
        replace_from_user_id=None,
        quick_move=None,
        db=db,
    )

    assert response.status_code == 303
    assert "msg_player_moved" in response.headers["location"]
    assert any(member.stage_id == 20 and member.user_id == 55 for member in db.memberships)


@pytest.mark.asyncio
async def test_admin_reassign_user_accepts_empty_string_stage_and_group_without_422() -> None:
    user = User(id=88, nickname="quick", basket=Basket.BISHOP.value)
    target_stage = PlayoffStage(id=31, key="stage_2", title="Stage 2", stage_size=16, stage_order=1)
    db = _FakeDB(user=user, stage=target_stage, memberships=[])

    response = await web.admin_reassign_user(
        user_id=88,
        target_stage_id="",
        target_group_number="",
        replace_from_user_id="",
        quick_move="to_reserve",
        db=db,
    )

    assert response.status_code == 303
    assert "msg_status_ok" in response.headers["location"]
    assert db.commit.await_count == 1
    assert user.basket == Basket.BISHOP_RESERVE.value


@pytest.mark.asyncio
async def test_admin_reassign_user_requires_stage_for_stage_move_without_quick_action() -> None:
    user = User(id=90, nickname="nostage", basket=Basket.ROOK.value)
    target_stage = PlayoffStage(id=33, key="stage_2", title="Stage 2", stage_size=16, stage_order=1)
    db = _FakeDB(user=user, stage=target_stage, memberships=[])

    response = await web.admin_reassign_user(
        user_id=90,
        target_stage_id="",
        target_group_number="",
        replace_from_user_id="",
        quick_move=None,
        db=db,
    )

    assert response.status_code == 303
    assert "msg_operation_failed" in response.headers["location"]
    assert "details=target_stage_id_required" in response.headers["location"]
    assert db.rollback.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quick_move", "expected_basket"),
    [
        ("to_main", Basket.ROOK.value),
        ("to_reserve", Basket.ROOK_RESERVE.value),
    ],
)
async def test_admin_reassign_user_quick_move_works_without_selected_stage(quick_move: str, expected_basket: str) -> None:
    user = User(id=89, nickname="quick2", basket=Basket.ROOK_RESERVE.value)
    target_stage = PlayoffStage(id=32, key="stage_2", title="Stage 2", stage_size=16, stage_order=1)
    db = _FakeDB(user=user, stage=target_stage, memberships=[])

    response = await web.admin_reassign_user(
        user_id=89,
        target_stage_id="",
        target_group_number="",
        replace_from_user_id="",
        quick_move=quick_move,
        db=db,
    )

    assert response.status_code == 303
    assert "msg_status_ok" in response.headers["location"]
    assert db.commit.await_count == 1
    assert user.basket == expected_basket


@pytest.mark.asyncio
async def test_admin_reassign_user_returns_no_changes_when_stage_and_group_same() -> None:
    user = User(id=91, nickname="same", basket=Basket.ROOK.value)
    target_stage = PlayoffStage(id=34, key="stage_2", title="Stage 2", stage_size=32, stage_order=1)
    membership = PlayoffParticipant(stage_id=34, user_id=91, seed=10)
    db = _FakeDB(user=user, stage=target_stage, memberships=[membership])

    response = await web.admin_reassign_user(
        user_id=91,
        target_stage_id="34",
        target_group_number="2",
        replace_from_user_id="",
        quick_move=None,
        reassign_action="move_stage",
        db=db,
    )

    assert response.status_code == 303
    assert "msg_status_ok" in response.headers["location"]
    assert "details=no_changes" in response.headers["location"]
    assert db.rollback.await_count == 1
    assert db.commit.await_count == 0


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


def test_admin_users_page_reassign_ui_does_not_require_manual_user_id(monkeypatch) -> None:
    class _DB:
        async def scalars(self, statement):
            sql = str(statement)
            if "FROM users" in sql:
                return _ScalarResult([User(id=7, nickname="u7")])
            if "FROM playoff_stages" in sql:
                return _ScalarResult(
                    [
                        PlayoffStage(id=11, key="stage_1", title="Stage 1", stage_size=16, stage_order=0),
                        PlayoffStage(id=12, key="stage_2", title="Stage 2", stage_size=16, stage_order=1),
                    ]
                )
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
    html = response.body.decode("utf-8")

    assert response.status_code == 200
    assert "replace_from_user_id" not in html
    assert "user-reassign-stage" in html
    assert "user-reassign-group" in html
    assert "Stage 1" in html
    assert "Stage 2" in html


def test_admin_users_page_reassign_ui_has_fallback_stage_options_when_playoff_stages_empty(monkeypatch) -> None:
    class _DB:
        async def scalars(self, statement):
            sql = str(statement)
            if "FROM users" in sql:
                return _ScalarResult([User(id=9, nickname="u9")])
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
    html = response.body.decode("utf-8")

    assert response.status_code == 200
    assert "- stage -" in html
    assert "Stage 2" in html
    assert "Stage 3" in html
    assert "Final" in html
    assert 'const stageGroupOptions = {' in html
    assert '"stage_2": [1, 2, 3, 4]' in html
    assert '"stage_1_4": [1, 2]' in html
    assert '"stage_final": [1]' in html



def test_admin_users_page_reassign_ui_has_explicit_labels_and_tooltips(monkeypatch) -> None:
    class _DB:
        async def scalars(self, statement):
            sql = str(statement)
            if "FROM users" in sql:
                return _ScalarResult([User(id=10, nickname="u10")])
            if "FROM playoff_stages" in sql:
                return _ScalarResult([PlayoffStage(id=21, key="stage_2", title="Stage 2", stage_size=16, stage_order=1)])
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
    html = response.body.decode("utf-8")

    assert response.status_code == 200
    assert "Basket" in html
    assert "Stage/Group" in html
    assert "To Main Basket" in html
    assert "To Reserve Basket" in html
    assert "Move to Stage/Group" in html
    assert "Direct invite" not in html
    assert 'title="Move user to the main basket pair"' in html
    assert 'title="Move user to the reserve basket pair"' in html
    assert 'title="Move user to selected stage and optionally selected group"' in html


@pytest.mark.asyncio
async def test_admin_reassign_user_accepts_stage_key_and_creates_stage_when_missing() -> None:
    user = User(id=92, nickname="missing-stage", basket=Basket.ROOK.value)
    db = _FakeDB(user=user, stage=None, memberships=[])

    response = await web.admin_reassign_user(
        user_id=92,
        target_stage_id="stage_2",
        target_group_number="1",
        replace_from_user_id="",
        quick_move=None,
        db=db,
    )

    assert response.status_code == 303
    assert "msg_player_moved" in response.headers["location"]
    assert db.stage is not None
    assert db.stage.key == "stage_2"
