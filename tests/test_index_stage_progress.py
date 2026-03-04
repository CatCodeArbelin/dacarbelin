from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeIndexDB:
    def __init__(
        self,
        *,
        total_participants=0,
        stage_1_count=0,
        stage_2_count=0,
        stage_3_count=0,
        active_playoff_key=None,
    ):
        self.total_participants = total_participants
        self.stage_1_count = stage_1_count
        self.stage_2_count = stage_2_count
        self.stage_3_count = stage_3_count
        self.active_playoff_key = active_playoff_key

    async def scalars(self, statement):
        sql = str(statement)
        if "FROM chat_messages" in sql:
            return _FakeScalarResult([])
        raise AssertionError(f"Unexpected scalars query: {sql}")

    async def scalar(self, statement):
        sql = str(statement)
        params = statement.compile().params

        if "FROM site_settings" in sql:
            return None
        if "FROM chat_settings" in sql:
            return None
        if "count(users.id)" in sql:
            return self.total_participants
        if "FROM group_members" in sql and "tournament_groups.stage" in sql:
            return self.stage_1_count
        if "FROM playoff_participants" in sql and params.get("key_1") == "stage_2":
            return self.stage_2_count
        if "FROM playoff_participants" in sql and params.get("key_1") == "stage_1_4":
            return self.stage_3_count
        if "SELECT playoff_stages.key" in sql and "playoff_stages.is_started" in sql:
            return self.active_playoff_key

        raise AssertionError(f"Unexpected scalar query: {sql} | params={params}")



def test_index_stage_progress_fallback_for_empty_tournament() -> None:
    fake_db = _FakeIndexDB()

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert "1 Stage (0%)" in response.text
    assert "2 Stage (0%)" in response.text
    assert "3 Stage (0%)" in response.text
    assert "Final LIVE on Twitch" in response.text
    assert response.text.index("Final LIVE on Twitch") < response.text.index('id="chat"')



def test_index_stage_progress_uses_active_playoff_stage_highlight() -> None:
    fake_db = _FakeIndexDB(total_participants=100, stage_1_count=80, stage_2_count=32, stage_3_count=16, active_playoff_key="stage_2")

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert "1 Stage (80%)" in response.text
    assert "2 Stage (32%)" in response.text
    assert 'text-contrast-neon">2 Stage (32%)' in response.text
