"""Проверяет поведение admin middleware для /admin и /admin/."""

import sys
import types

from fastapi import APIRouter
from fastapi.testclient import TestClient

stub_web_router = types.ModuleType("app.routers.web")
stub_web_router.router = APIRouter()
sys.modules.setdefault("app.routers.web", stub_web_router)

from app.core.admin_session import create_judge_login_token
from app.main import app


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


def test_judge_token_auth_works_once_then_fails() -> None:
    client = TestClient(app)
    judge_token = create_judge_login_token()

    success_response = client.get(f"/admin?judge_token={judge_token}", follow_redirects=False)
    assert success_response.status_code == 303
    assert success_response.headers["location"] == "/admin"

    client.cookies.clear()
    replay_response = client.get(f"/admin?judge_token={judge_token}", follow_redirects=False)
    assert replay_response.status_code == 303
    assert replay_response.headers["location"] == "/admin/login?msg=msg_admin_login_failed"
