"""Проверяет удаление пользователя из админ-панели."""

from fastapi.testclient import TestClient

from app.core.admin_session import ADMIN_SESSION_COOKIE, create_admin_session_cookie
from app.main import app
from app.models.user import User
from app.routers import web


class _FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


def test_admin_delete_user_success(monkeypatch) -> None:
    state = {"helper_called": False, "committed": False}
    target_user = _FakeUser(user_id=17)

    async def fake_get(self, model, pk):
        return target_user if pk == 17 else None

    async def fake_delete_helper(db, *, user):
        state["helper_called"] = True
        assert user is target_user

    async def fake_commit(self):
        state["committed"] = True

    monkeypatch.setattr(web.AsyncSession, "get", fake_get, raising=False)
    monkeypatch.setattr(web, "_delete_user_with_dependencies", fake_delete_helper)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post("/admin/user/delete", data={"user_id": "17"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/users?msg=msg_user_deleted"
    assert state == {"helper_called": True, "committed": True}


def test_admin_delete_user_not_found(monkeypatch) -> None:
    state = {"committed": False}

    async def fake_get(self, model, pk):
        return None

    async def fake_commit(self):
        state["committed"] = True

    monkeypatch.setattr(web.AsyncSession, "get", fake_get, raising=False)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post("/admin/user/delete", data={"user_id": "999"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/users?msg=msg_user_delete_not_found"
    assert state["committed"] is False


def test_admin_delete_user_rolls_back_on_error(monkeypatch) -> None:
    state = {"rolled_back": False, "committed": False}
    target_user = _FakeUser(user_id=21)

    async def fake_get(self, model, pk):
        return target_user

    async def fake_delete_helper(db, *, user):
        raise RuntimeError("delete failed")

    async def fake_commit(self):
        state["committed"] = True

    async def fake_rollback(self):
        state["rolled_back"] = True

    monkeypatch.setattr(web.AsyncSession, "get", fake_get, raising=False)
    monkeypatch.setattr(web, "_delete_user_with_dependencies", fake_delete_helper)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)
    monkeypatch.setattr(web.AsyncSession, "rollback", fake_rollback, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post("/admin/user/delete", data={"user_id": "21"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/users?msg=msg_user_delete_failed"
    assert state == {"rolled_back": True, "committed": False}


class _FakeDeleteDb:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.deleted = None

    async def execute(self, statement):
        self.executed.append(str(statement))

    async def delete(self, instance):
        self.deleted = instance


def test_delete_user_with_dependencies_executes_explicit_cleanup() -> None:
    db = _FakeDeleteDb()
    user = User(
        id=55,
        nickname="User",
        steam_input="s",
        steam_id="sid",
        game_nickname="g",
        current_rank="c",
        highest_rank="h",
        telegram=None,
        discord=None,
        basket="rook",
        direct_invite_stage=None,
        direct_invite_group_number=None,
        extra_data=None,
    )

    import asyncio

    asyncio.run(web._delete_user_with_dependencies(db, user=user))

    sql = "\n".join(db.executed)
    assert "DELETE FROM group_game_results" in sql
    assert "DELETE FROM group_manual_tie_breaks" in sql
    assert "DELETE FROM group_members" in sql
    assert "DELETE FROM playoff_participants" in sql
    assert "UPDATE playoff_matches SET winner_user_id" in sql
    assert "UPDATE playoff_matches SET manual_winner_user_id" in sql
    assert "UPDATE playoff_stages SET final_candidate_user_id" in sql
    assert db.deleted is user
