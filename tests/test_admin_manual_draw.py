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

    monkeypatch.setattr(web, "create_manual_draw", fake_create_manual_draw)

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
