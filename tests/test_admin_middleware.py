"""Проверяет поведение admin middleware для /admin и /admin/."""

import sys
import types

from fastapi import APIRouter
from fastapi.testclient import TestClient

stub_web_router = types.ModuleType("app.routers.web")
stub_web_router.router = APIRouter()
sys.modules.setdefault("app.routers.web", stub_web_router)

from app.main import app
import app.main as main_module


def test_admin_key_auth_works_for_admin_path_without_trailing_slash() -> None:
    client = TestClient(app)

    response = client.get("/admin?admin_key=test_admin", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin"
    assert "admin_session=" in response.headers.get("set-cookie", "")


def test_admin_key_auth_works_for_admin_path_with_trailing_slash() -> None:
    client = TestClient(app)

    response = client.get("/admin/?admin_key=test_admin", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin"
    assert "admin_session=" in response.headers.get("set-cookie", "")


def test_admin_key_auth_redirects_to_login_on_invalid_admin_key() -> None:
    client = TestClient(app)

    response = client.get("/admin?admin_key=invalid", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login?msg=msg_admin_login_failed"


def test_judge_token_auth_works_once_then_fails(monkeypatch) -> None:
    client = TestClient(app)
    state = {"used": False}

    async def fake_consume_persisted_judge_token(token: str | None) -> bool:
        if token != "judge-token" or state["used"]:
            return False
        state["used"] = True
        return True

    monkeypatch.setattr(main_module, "consume_persisted_judge_token", fake_consume_persisted_judge_token)

    success_response = client.get("/admin?judge_token=judge-token", follow_redirects=False)
    assert success_response.status_code == 303
    assert success_response.headers["location"] == "/admin"

    client.cookies.clear()
    replay_response = client.get("/admin?judge_token=judge-token", follow_redirects=False)
    assert replay_response.status_code == 303
    assert replay_response.headers["location"] == "/admin/login?msg=msg_admin_login_failed"
