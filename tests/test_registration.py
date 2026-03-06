import json

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.routers import web


class _FakeExecuteResult:
    def all(self):
        return []


class _FakeRegisterDB:
    def __init__(self):
        self.added = []
        self.committed = False

    async def scalar(self, statement):
        return None

    async def execute(self, statement):
        return _FakeExecuteResult()

    def add(self, instance):
        self.added.append(instance)

    async def commit(self):
        self.committed = True


def test_register_uses_input_nickname(monkeypatch):
    fake_db = _FakeRegisterDB()

    async def override_get_db():
        yield fake_db

    async def fake_tournament_started(db):
        return False

    async def fake_registration_open(db):
        return True

    async def fake_normalize_steam_id(steam_input):
        return "76561198000000000"

    async def fake_fetch_autochess_data(steam_id):
        return {
            "game_nickname": "AutoNick",
            "current_rank": "Knight",
            "highest_rank": "King",
            "raw": {"source": "test"},
        }

    monkeypatch.setattr(web, "get_tournament_started", fake_tournament_started)
    monkeypatch.setattr(web, "get_registration_open", fake_registration_open)
    monkeypatch.setattr(web, "normalize_steam_id", fake_normalize_steam_id)
    monkeypatch.setattr(web, "fetch_autochess_data", fake_fetch_autochess_data)
    monkeypatch.setattr(web, "pick_basket", lambda *args, **kwargs: "new")
    monkeypatch.setattr(web, "allocate_basket", lambda *args, **kwargs: "new")

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/register",
                data={
                    "steam_input": "https://steamcommunity.com/profiles/76561198000000000/",
                    "telegram": "@telegram",
                    "nickname": "ManualNick",
                    "rules_ack": "1",
                },
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 303
    assert fake_db.committed is True
    assert len(fake_db.added) == 1

    user = fake_db.added[0]
    assert user.nickname == "ManualNick"
    assert user.discord is None
    assert user.telegram == "@telegram"
    assert json.loads(user.extra_data) == {"source": "test"}


def test_register_requires_nickname(monkeypatch):
    fake_db = _FakeRegisterDB()

    async def override_get_db():
        yield fake_db

    async def fake_tournament_started(db):
        return False

    async def fake_registration_open(db):
        return True

    async def fake_normalize_steam_id(steam_input):
        return "76561198000000000"

    async def fake_fetch_autochess_data(steam_id):
        return {
            "game_nickname": "AutoNick",
            "current_rank": "Pawn",
            "highest_rank": "Pawn",
            "raw": {},
        }

    monkeypatch.setattr(web, "get_tournament_started", fake_tournament_started)
    monkeypatch.setattr(web, "get_registration_open", fake_registration_open)
    monkeypatch.setattr(web, "normalize_steam_id", fake_normalize_steam_id)
    monkeypatch.setattr(web, "fetch_autochess_data", fake_fetch_autochess_data)
    monkeypatch.setattr(web, "pick_basket", lambda *args, **kwargs: "new")
    monkeypatch.setattr(web, "allocate_basket", lambda *args, **kwargs: "new")

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/register",
                data={"steam_input": "76561198000000000"},
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 422


def test_register_rejects_blank_nickname(monkeypatch):
    fake_db = _FakeRegisterDB()

    async def override_get_db():
        yield fake_db

    async def fake_tournament_started(db):
        return False

    async def fake_registration_open(db):
        return True

    async def fake_normalize_steam_id(steam_input):
        return "76561198000000000"

    async def fake_fetch_autochess_data(steam_id):
        return {
            "game_nickname": "AutoNick",
            "current_rank": "Pawn",
            "highest_rank": "Pawn",
            "raw": {},
        }

    monkeypatch.setattr(web, "get_tournament_started", fake_tournament_started)
    monkeypatch.setattr(web, "get_registration_open", fake_registration_open)
    monkeypatch.setattr(web, "normalize_steam_id", fake_normalize_steam_id)
    monkeypatch.setattr(web, "fetch_autochess_data", fake_fetch_autochess_data)
    monkeypatch.setattr(web, "pick_basket", lambda *args, **kwargs: "new")
    monkeypatch.setattr(web, "allocate_basket", lambda *args, **kwargs: "new")

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/register",
                data={"steam_input": "76561198000000000", "nickname": "   ", "rules_ack": "1"},
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 303
    assert response.headers["location"].endswith("msg=msg_invalid_request")
    assert not fake_db.added


def test_register_rejects_too_long_nickname(monkeypatch):
    fake_db = _FakeRegisterDB()

    async def override_get_db():
        yield fake_db

    async def fake_tournament_started(db):
        return False

    async def fake_registration_open(db):
        return True

    async def fake_normalize_steam_id(steam_input):
        return "76561198000000000"

    async def fake_fetch_autochess_data(steam_id):
        return {
            "game_nickname": "AutoNick",
            "current_rank": "Pawn",
            "highest_rank": "Pawn",
            "raw": {},
        }

    monkeypatch.setattr(web, "get_tournament_started", fake_tournament_started)
    monkeypatch.setattr(web, "get_registration_open", fake_registration_open)
    monkeypatch.setattr(web, "normalize_steam_id", fake_normalize_steam_id)
    monkeypatch.setattr(web, "fetch_autochess_data", fake_fetch_autochess_data)
    monkeypatch.setattr(web, "pick_basket", lambda *args, **kwargs: "new")
    monkeypatch.setattr(web, "allocate_basket", lambda *args, **kwargs: "new")

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/register",
                data={"steam_input": "76561198000000000", "nickname": "N" * 121, "rules_ack": "1"},
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 303
    assert response.headers["location"].endswith("msg=msg_invalid_request")
    assert not fake_db.added
