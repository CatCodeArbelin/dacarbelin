"""Проверяет поведение admin middleware для /admin и /admin/."""

import sys
import types

from fastapi import APIRouter
from fastapi.testclient import TestClient

stub_web_router = types.ModuleType("app.routers.web")
stub_web_router.router = APIRouter()
sys.modules.setdefault("app.routers.web", stub_web_router)

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
