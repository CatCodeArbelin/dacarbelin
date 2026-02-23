"""Проверяет ручную жеребьевку через admin API с выбором участников из формы."""
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.core.admin_session import ADMIN_SESSION_COOKIE, create_admin_session_cookie
from app.main import app
from app.routers import web


def test_admin_manual_draw_accepts_user_ids_array(monkeypatch) -> None:
    """Проверяет позитивный сценарий `test_admin_manual_draw_accepts_user_ids_array`.
    Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
    Запуск: `pytest tests/test_admin_manual_draw.py -q` и `pytest tests/test_admin_manual_draw.py -k "test_admin_manual_draw_accepts_user_ids_array" -q`."""
    captured: dict[str, int | list[int]] = {}

    async def fake_create_manual_draw(db, group_count: int, user_ids: list[int]) -> None:
        captured["group_count"] = group_count
        captured["user_ids"] = user_ids

    async def fake_set_draw_applied(db, value: bool):
        return None

    async def fake_commit(self):
        return None

    monkeypatch.setattr(web, "create_manual_draw", fake_create_manual_draw)
    monkeypatch.setattr(web, "set_draw_applied", fake_set_draw_applied)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/draw/manual",
            data={"group_count": "2", "user_ids[]": ["11", "12"]},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_status_ok"
    assert captured == {"group_count": 2, "user_ids": [11, 12]}


def test_admin_auto_draw_redirect_contains_details_on_error(monkeypatch) -> None:
    """Проверяет негативный сценарий `test_admin_auto_draw_redirect_contains_details_on_error`.
    Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
    Запуск: `pytest tests/test_admin_manual_draw.py -q` и `pytest tests/test_admin_manual_draw.py -k "test_admin_auto_draw_redirect_contains_details_on_error" -q`."""
    async def fake_create_auto_draw(db):
        return False, "Автожеребьевка недоступна: требуется минимум 56 валидных участников (формат 7x8)."

    monkeypatch.setattr(web, "create_auto_draw", fake_create_auto_draw)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post("/admin/draw/auto", follow_redirects=False)

    assert response.status_code == 303
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)

    assert parsed.path == "/admin"
    assert query["msg"] == ["msg_status_warn"]
    assert query["details"] == ["Автожеребьевка недоступна: требуется минимум 56 валидных участников (формат 7x8)."]


def test_admin_apply_draw_sets_draw_applied_flag(monkeypatch) -> None:
    """Проверяет позитивный сценарий применения жеребьевки и установки флага."""
    state: dict[str, bool] = {"committed": False, "set_true": False}

    async def fake_validate_group_draw_integrity(db):
        return True, None

    async def fake_set_draw_applied(db, value: bool):
        state["set_true"] = value

    async def fake_commit(self):
        state["committed"] = True

    monkeypatch.setattr(web, "validate_group_draw_integrity", fake_validate_group_draw_integrity)
    monkeypatch.setattr(web, "set_draw_applied", fake_set_draw_applied)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post("/admin/draw/apply", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_status_ok"
    assert state == {"committed": True, "set_true": True}


def test_admin_start_tournament_requires_applied_draw(monkeypatch) -> None:
    """Проверяет guard на запуск турнира без применения жеребьевки."""

    async def fake_get_draw_applied(db):
        return False

    monkeypatch.setattr(web, "get_draw_applied", fake_get_draw_applied)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post("/admin/tournament/start", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_operation_failed&details=draw_not_applied"


def test_admin_manual_draw_resets_draw_applied(monkeypatch) -> None:
    """Проверяет сброс флага draw_applied после ручной жеребьевки."""
    state: dict[str, bool] = {"set_false": False, "committed": False}

    async def fake_create_manual_draw(db, group_count: int, user_ids: list[int]) -> None:
        return None

    async def fake_set_draw_applied(db, value: bool):
        state["set_false"] = (value is False)

    async def fake_commit(self):
        state["committed"] = True

    monkeypatch.setattr(web, "create_manual_draw", fake_create_manual_draw)
    monkeypatch.setattr(web, "set_draw_applied", fake_set_draw_applied)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post("/admin/draw/manual", data={"group_count": "2", "user_ids[]": ["11", "12"]}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_status_ok"
    assert state == {"set_false": True, "committed": True}
