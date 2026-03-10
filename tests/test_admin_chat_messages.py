"""Проверяет админ-операции редактирования и удаления сообщений чата."""

from datetime import datetime

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



def test_send_chat_with_cyrillic_temp_nick_sets_ascii_sender_token(monkeypatch) -> None:
    """Проверяет, что отправка сообщения с кириллическим ником не падает и выставляет ASCII cookie."""

    class _FakeSendChatSettings:
        is_enabled = True
        max_length = 100
        cooldown_seconds = 10

    state = {"committed": False, "saved_message": None}

    async def fake_get_chat_settings(db):
        return _FakeSendChatSettings()

    async def fake_scalar(self, statement):
        return None

    def fake_add(self, instance):
        state["saved_message"] = instance

    async def fake_commit(self):
        state["committed"] = True

    monkeypatch.setattr(web, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(web.AsyncSession, "scalar", fake_scalar, raising=False)
    monkeypatch.setattr(web.AsyncSession, "add", fake_add, raising=False)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)

    with TestClient(app) as client:
        response = client.post(
            "/chat/send",
            data={"temp_nick": "Кириллица", "nick_color": "#00d4ff", "message": "Привет"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/#chat"
    assert state["committed"] is True
    assert state["saved_message"] is not None
    assert state["saved_message"].temp_nick == "Кириллица"
    assert web.CHAT_SENDER_TOKEN_RE.fullmatch(state["saved_message"].sender_token)
    assert "chat_sender=" in response.headers["set-cookie"]
    assert "chat_nick=" in response.headers["set-cookie"]
    cookie_token = response.headers["set-cookie"].split("chat_sender=", 1)[1].split(";", 1)[0]
    assert web.CHAT_SENDER_TOKEN_RE.fullmatch(cookie_token)


def test_send_chat_rejects_reserved_nicks(monkeypatch) -> None:
    """Проверяет, что обычный пользователь не может использовать служебные ники."""

    class _FakeSendChatSettings:
        is_enabled = True
        max_length = 100
        cooldown_seconds = 0

    async def fake_get_chat_settings(db):
        return _FakeSendChatSettings()

    monkeypatch.setattr(web, "get_chat_settings", fake_get_chat_settings)

    with TestClient(app) as client:
        response = client.post(
            "/chat/send",
            data={"temp_nick": "@arbelin", "nick_color": "#00d4ff", "message": "hello"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/?msg=msg_chat_nick_reserved"


def test_admin_send_chat_uses_selected_sender_and_sets_cookie(monkeypatch) -> None:
    """Проверяет отправку админ-сообщения от выбранного имени и сохранение выбора в cookie."""

    class _FakeSendChatSettings:
        max_length = 100

    state = {"published": False, "saved_message": None}

    async def fake_get_chat_settings(db):
        return _FakeSendChatSettings()

    def fake_add(self, instance):
        state["saved_message"] = instance

    async def fake_commit(self):
        return None

    async def fake_publish():
        state["published"] = True

    monkeypatch.setattr(web, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(web.AsyncSession, "add", fake_add, raising=False)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)
    monkeypatch.setattr(web.chat_event_broker, "publish", fake_publish)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/chat/send",
            data={"message": "admin hello", "sender_nick": "@loyrensss"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_admin_chat_message_saved"
    assert state["published"] is True
    assert state["saved_message"] is not None
    assert state["saved_message"].temp_nick == "@Loyrensss"
    assert state["saved_message"].nick_color == "#b084ff"
    assert "admin_chat_sender=%40Loyrensss" in response.headers["set-cookie"]



def test_admin_clear_chat_messages_success(monkeypatch) -> None:
    """Проверяет массовую очистку сообщений чата админом."""
    state = {"executed": False, "committed": False, "published": False}

    async def fake_execute(self, statement):
        state["executed"] = str(statement).startswith("DELETE FROM chat_messages")

    async def fake_commit(self):
        state["committed"] = True

    async def fake_publish():
        state["published"] = True

    monkeypatch.setattr(web.AsyncSession, "execute", fake_execute, raising=False)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)
    monkeypatch.setattr(web.chat_event_broker, "publish", fake_publish)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post("/admin/chat/messages/clear", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_admin_chat_messages_cleared"
    assert state == {"executed": True, "committed": True, "published": True}


def test_admin_send_chat_clear_command_clears_messages(monkeypatch) -> None:
    """Проверяет поддержку команды /clear в отправке админ-сообщений."""

    class _FakeSendChatSettings:
        max_length = 100

    state = {"executed": False, "committed": False, "published": False, "added": False}

    async def fake_get_chat_settings(db):
        return _FakeSendChatSettings()

    async def fake_execute(self, statement):
        state["executed"] = str(statement).startswith("DELETE FROM chat_messages")

    async def fake_commit(self):
        state["committed"] = True

    async def fake_publish():
        state["published"] = True

    def fake_add(self, instance):
        state["added"] = True

    monkeypatch.setattr(web, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(web.AsyncSession, "execute", fake_execute, raising=False)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)
    monkeypatch.setattr(web.AsyncSession, "add", fake_add, raising=False)
    monkeypatch.setattr(web.chat_event_broker, "publish", fake_publish)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/chat/send",
            data={"message": "/clear", "sender_nick": "@Admin"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_admin_chat_messages_cleared"
    assert state == {"executed": True, "committed": True, "published": True, "added": False}

def test_send_chat_publishes_stream_event(monkeypatch) -> None:
    """Проверяет публикацию SSE-события после пользовательского сообщения."""

    class _FakeSendChatSettings:
        is_enabled = True
        max_length = 100
        cooldown_seconds = 0

    state = {"published": False}

    async def fake_get_chat_settings(db):
        return _FakeSendChatSettings()

    async def fake_scalar(self, statement):
        return None

    def fake_add(self, instance):
        return None

    async def fake_commit(self):
        return None

    async def fake_publish():
        state["published"] = True

    monkeypatch.setattr(web, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(web.AsyncSession, "scalar", fake_scalar, raising=False)
    monkeypatch.setattr(web.AsyncSession, "add", fake_add, raising=False)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)
    monkeypatch.setattr(web.chat_event_broker, "publish", fake_publish)

    with TestClient(app) as client:
        response = client.post(
            "/chat/send",
            data={"temp_nick": "Tester", "nick_color": "#00d4ff", "message": "hello"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert state["published"] is True


def test_admin_send_chat_publishes_stream_event(monkeypatch) -> None:
    """Проверяет публикацию SSE-события после сообщения админа."""

    class _FakeSendChatSettings:
        max_length = 100

    state = {"published": False}

    async def fake_get_chat_settings(db):
        return _FakeSendChatSettings()

    def fake_add(self, instance):
        return None

    async def fake_commit(self):
        return None

    async def fake_publish():
        state["published"] = True

    monkeypatch.setattr(web, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(web.AsyncSession, "add", fake_add, raising=False)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)
    monkeypatch.setattr(web.chat_event_broker, "publish", fake_publish)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/chat/send",
            data={"message": "admin hello"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_admin_chat_message_saved"
    assert state["published"] is True


def test_format_chat_message_source_variants() -> None:
    """Проверяет формат строки источника сообщения."""
    assert web.format_chat_message_source("TempNick", "127.0.0.1") == "TempNick (127.0.0.1)"
    assert (
        web.format_chat_message_source("TempNick", "127.0.0.1", city="Moscow", country="RU")
        == "TempNick(127.0.0.1 - Moscow, RU)"
    )
    assert web.format_chat_message_source("TempNick", "127.0.0.1", country="RU") == "TempNick(127.0.0.1 - RU)"


def test_admin_chat_page_renders_source_display(monkeypatch) -> None:
    """Проверяет вывод строки источника рядом с ником в админском чате."""

    class _FakeMessage:
        id = 11
        temp_nick = "Guest"
        message = "hello"
        ip_address = "203.0.113.9"
        created_at = datetime(2025, 1, 1, 12, 0, 0)

    class _FakeScalarResult:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    class _FakeChatSettingsPage:
        cooldown_seconds = 0
        max_length = 120
        is_enabled = True

    async def fake_get_or_create_chat_settings(db):
        return _FakeChatSettingsPage()

    async def fake_scalars(self, statement):
        return _FakeScalarResult([_FakeMessage()])

    monkeypatch.setattr(web, "get_or_create_chat_settings", fake_get_or_create_chat_settings)
    monkeypatch.setattr(web.AsyncSession, "scalars", fake_scalars, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        client.cookies.set(web.ADMIN_CHAT_SENDER_COOKIE, "@Loyrensss")
        response = client.get("/admin/chat")

    assert response.status_code == 200
    assert "Guest (203.0.113.9)" in response.text


def test_send_chat_uses_forwarded_for_ip(monkeypatch) -> None:
    """Проверяет, что для пользователя сохраняется IP из X-Forwarded-For."""

    class _FakeSendChatSettings:
        is_enabled = True
        max_length = 100
        cooldown_seconds = 0

    state = {"saved_message": None}

    async def fake_get_chat_settings(db):
        return _FakeSendChatSettings()

    async def fake_scalar(self, statement):
        return None

    def fake_add(self, instance):
        state["saved_message"] = instance

    async def fake_commit(self):
        return None

    async def fake_publish():
        return None

    monkeypatch.setattr(web, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(web.AsyncSession, "scalar", fake_scalar, raising=False)
    monkeypatch.setattr(web.AsyncSession, "add", fake_add, raising=False)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)
    monkeypatch.setattr(web.chat_event_broker, "publish", fake_publish)

    with TestClient(app) as client:
        response = client.post(
            "/chat/send",
            data={"temp_nick": "User", "nick_color": "#00d4ff", "message": "Привет"},
            headers={"X-Forwarded-For": "203.0.113.7, 172.18.0.1"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert state["saved_message"] is not None
    assert state["saved_message"].ip_address == "203.0.113.7"


def test_get_request_ip_address_prefers_x_real_ip_when_forwarded_for_missing() -> None:
    """Проверяет, что helper корректно берет IP из X-Real-IP."""

    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-real-ip", b"198.51.100.22")],
        "client": ("172.18.0.1", 12345),
        "scheme": "http",
        "server": ("testserver", 80),
    }
    request = Request(scope)

    assert web.get_request_ip_address(request) == "198.51.100.22"
