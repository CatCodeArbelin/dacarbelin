import os

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test_db")
os.environ.setdefault("ADMIN_KEY", "test_admin")

from app.db.session import get_db
from app.main import app
from app.models.user import Basket, User


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


def test_participants_direct_invites_shows_stage_2_user() -> None:
    stage_2_user = User(
        nickname="stage2_user",
        steam_input="stage2_input",
        steam_id="steam_stage2",
        game_nickname="stage2_game",
        current_rank="Pawn-1",
        highest_rank="Knight-1",
        basket=Basket.INVITED.value,
        direct_invite_stage="stage_2",
    )
    fake_db = _FakeDB(users=[stage_2_user])

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/participants?view=direct_invites")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert "stage2_user" in response.text
    assert fake_db.last_statement is not None

    compiled = str(fake_db.last_statement)
    assert "users.basket" in compiled
    assert "users.direct_invite_stage" in compiled


def test_participants_direct_invites_excludes_non_stage_2_invites() -> None:
    stage_2_user = User(
        nickname="visible_invite",
        steam_input="stage2_input_visible",
        steam_id="steam_stage2_visible",
        game_nickname="stage2_game_visible",
        current_rank="Pawn-1",
        highest_rank="Knight-1",
        basket=Basket.INVITED.value,
        direct_invite_stage="stage_2",
    )
    wrong_stage_user = User(
        nickname="hidden_invite",
        steam_input="stage3_input_hidden",
        steam_id="steam_stage3_hidden",
        game_nickname="stage3_game_hidden",
        current_rank="Pawn-1",
        highest_rank="Knight-1",
        basket=Basket.INVITED.value,
        direct_invite_stage="stage_3",
    )
    fake_db = _FakeDB(users=[stage_2_user])

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/participants?view=direct_invites")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert "visible_invite" in response.text
    assert wrong_stage_user.nickname not in response.text
    assert "/participants?view=direct_invites" in response.text
