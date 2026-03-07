"""Проверяет обновление пользователя из админ-панели."""

import asyncio

from fastapi.testclient import TestClient

from app.core.admin_session import ADMIN_SESSION_COOKIE, create_admin_session_cookie
from app.main import app
from app.models.user import User
from app.routers import web


def _build_user(*, user_id: int, direct_invite_stage: str | None, direct_invite_group_number: int | None) -> User:
    return User(
        id=user_id,
        nickname="User",
        steam_input="s",
        steam_id=f"sid-{user_id}",
        game_nickname="g",
        current_rank="c",
        highest_rank="h",
        telegram=None,
        discord=None,
        basket="rook",
        direct_invite_stage=direct_invite_stage,
        direct_invite_group_number=direct_invite_group_number,
        extra_data=None,
    )


def test_admin_update_user_preserves_direct_invite_stage_when_form_omits_it(monkeypatch) -> None:
    target_user = _build_user(user_id=7, direct_invite_stage="stage_2", direct_invite_group_number=2)
    state: dict[str, str | None] = {"direct_invite_stage": None}

    async def fake_get(self, model, pk):
        return target_user if pk == 7 else None

    async def fake_update_helper(db, **kwargs):
        state["direct_invite_stage"] = kwargs["direct_invite_stage"]
        return web.redirect_with_admin_users_msg("msg_status_ok")

    monkeypatch.setattr(web.AsyncSession, "get", fake_get, raising=False)
    monkeypatch.setattr(web, "_update_user_allowed_fields", fake_update_helper)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/user/update",
            data={"user_id": "7", "nickname": "User", "basket": "rook", "manual_points": "10"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/users?msg=msg_status_ok"
    assert state["direct_invite_stage"] == "stage_2"


class _FakeScalarResult:
    def all(self):
        return []


class _FakeUpdateDb:
    def __init__(self, user: User) -> None:
        self.user = user
        self.committed = False

    async def get(self, model, pk):
        if pk == self.user.id:
            return self.user
        return None

    async def scalars(self, statement):
        return _FakeScalarResult()

    async def commit(self):
        self.committed = True


def test_update_user_allowed_fields_clears_group_number_when_stage_is_cleared() -> None:
    user = _build_user(user_id=15, direct_invite_stage="stage_2", direct_invite_group_number=3)
    db = _FakeUpdateDb(user)

    response = asyncio.run(
        web._update_user_allowed_fields(
            db,
            user_id=15,
            nickname="Updated",
            basket="rook",
            direct_invite_stage=None,
            manual_points=None,
        )
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/users?msg=msg_status_ok"
    assert user.direct_invite_stage is None
    assert user.direct_invite_group_number is None
    assert db.committed is True
