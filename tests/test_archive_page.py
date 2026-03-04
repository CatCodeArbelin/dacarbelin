from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeArchiveDB:
    def __init__(self, archive_entries, tournament_archives):
        self._calls = 0
        self._archive_entries = archive_entries
        self._tournament_archives = tournament_archives

    async def scalars(self, statement):
        self._calls += 1
        if self._calls == 1:
            return _FakeScalarResult(self._archive_entries)
        return _FakeScalarResult(self._tournament_archives)


def test_archive_page_renders_bracket_grid_without_raw_json_dump():
    modern_payload = (
        '[{"key":"stage_2","title":"1/4","participants":[{"user_id":1,"nickname":"Alpha","seed":1,"points":12},'
        '{"user_id":2,"nickname":"Bravo","seed":2,"points":9}],'
        '"matches":[{"group_number":1,"match_number":1,"state":"finished","winner_user_id":1}]}]'
    )

    legacy_entry = SimpleNamespace(
        title="Legacy cup",
        season="S0",
        summary="old format",
        champion_name="Retro",
        link_url="",
        bracket_payload="not-a-json-payload",
    )
    modern_archive = SimpleNamespace(
        title="Modern cup",
        season="S1",
        winner_nickname="Alpha",
        created_at=datetime(2024, 1, 1),
        bracket_payload_json=modern_payload,
    )

    fake_db = _FakeArchiveDB([legacy_entry], [modern_archive])

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/archive")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert "archive-bracket" in response.text
    assert "archive-bracket-column" in response.text
    assert "<pre" not in response.text
    assert "winner_user_id" not in response.text
    assert "Сетка недоступна" in response.text
