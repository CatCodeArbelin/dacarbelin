"""Проверяет админ-операции редактирования и удаления сообщений чата."""

from fastapi.testclient import TestClient

from app.core.admin_session import ADMIN_SESSION_COOKIE, create_admin_session_cookie
from app.main import app
from app.routers import web


class _FakeChatMessage:
    def __init__(self, message_id: int, temp_nick: str, message: str) -> None:
        self.id = message_id
        self.temp_nick = temp_nick
        self.message = message


class _FakeChatSettings:
    def __init__(self, max_length: int) -> None:
        self.max_length = max_length


def test_admin_chat_message_update_success(monkeypatch) -> None:
    """Проверяет успешное обновление сообщения админом."""
    target_message = _FakeChatMessage(message_id=7, temp_nick="old", message="old message")
    state = {"committed": False}

    async def fake_get(self, model, pk):
        return target_message if pk == 7 else None

    async def fake_get_chat_settings(db):
        return _FakeChatSettings(max_length=50)

    async def fake_commit(self):
        state["committed"] = True

    monkeypatch.setattr(web.AsyncSession, "get", fake_get, raising=False)
    monkeypatch.setattr(web, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/chat/message/update",
            data={"message_id": "7", "temp_nick": "new nick", "message": "new message"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_admin_chat_message_saved"
    assert target_message.temp_nick == "new nick"
    assert target_message.message == "new message"
    assert state["committed"] is True


def test_admin_chat_message_update_rejects_too_long_text(monkeypatch) -> None:
    """Проверяет валидацию длины сообщения при редактировании админом."""
    target_message = _FakeChatMessage(message_id=8, temp_nick="old", message="old")
    state = {"committed": False}

    async def fake_get(self, model, pk):
        return target_message if pk == 8 else None

    async def fake_get_chat_settings(db):
        return _FakeChatSettings(max_length=5)

    async def fake_commit(self):
        state["committed"] = True

    monkeypatch.setattr(web.AsyncSession, "get", fake_get, raising=False)
    monkeypatch.setattr(web, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/chat/message/update",
            data={"message_id": "8", "temp_nick": "new", "message": "123456"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_message_too_long"
    assert target_message.temp_nick == "old"
    assert target_message.message == "old"
    assert state["committed"] is False


def test_admin_chat_message_delete_success(monkeypatch) -> None:
    """Проверяет успешное удаление сообщения админом."""
    target_message = _FakeChatMessage(message_id=9, temp_nick="nick", message="msg")
    state = {"deleted": False, "committed": False}

    async def fake_get(self, model, pk):
        return target_message if pk == 9 else None

    async def fake_delete(self, instance):
        state["deleted"] = instance is target_message

    async def fake_commit(self):
        state["committed"] = True

    monkeypatch.setattr(web.AsyncSession, "get", fake_get, raising=False)
    monkeypatch.setattr(web.AsyncSession, "delete", fake_delete, raising=False)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/chat/message/delete",
            data={"message_id": "9"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_admin_chat_message_deleted"
    assert state == {"deleted": True, "committed": True}
