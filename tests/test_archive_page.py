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
    assert "archive-tree" in response.text
    assert "archive-tree-stage" in response.text
    assert "<pre" not in response.text
    assert "winner_user_id" not in response.text
    assert "Сетка недоступна" in response.text
    assert "Чемпион:" in response.text
    assert "★ Alpha" in response.text
    assert "archive-tree-badge-schedule" in response.text


def test_archive_page_highlights_group_and_final_podium_in_archive_tree():
    modern_payload = (
        '['
        '{"key":"group_stage","title":"Groups","participants":['
        '{"user_id":1,"nickname":"A","seed":1,"points":20},'
        '{"user_id":2,"nickname":"B","seed":2,"points":10},'
        '{"user_id":3,"nickname":"C","seed":3,"points":30},'
        '{"user_id":4,"nickname":"D","seed":4,"points":15},'
        '{"user_id":5,"nickname":"E","seed":5,"points":5},'
        '{"user_id":6,"nickname":"F","seed":6,"points":25},'
        '{"user_id":7,"nickname":"G","seed":7,"points":8},'
        '{"user_id":8,"nickname":"H","seed":8,"points":12}'
        ']},'
        '{"key":"stage_2","title":"Stage 2","participants":['
        '{"user_id":11,"nickname":"P1","seed":1,"points":1},'
        '{"user_id":12,"nickname":"P2","seed":2,"points":2},'
        '{"user_id":13,"nickname":"P3","seed":3,"points":3},'
        '{"user_id":14,"nickname":"P4","seed":4,"points":4},'
        '{"user_id":15,"nickname":"P5","seed":5,"points":5}'
        ']},'
        '{"key":"stage_1_4","title":"Stage 1/4","participants":['
        '{"user_id":21,"nickname":"Q1","seed":1,"points":14},'
        '{"user_id":22,"nickname":"Q2","seed":2,"points":11},'
        '{"user_id":23,"nickname":"Q3","seed":3,"points":9},'
        '{"user_id":24,"nickname":"Q4","seed":4,"points":8},'
        '{"user_id":25,"nickname":"Q5","seed":5,"points":7}'
        ']},'
        '{"key":"stage_final","title":"Final","participants":['
        '{"user_id":31,"nickname":"Winner","seed":1,"points":7},'
        '{"user_id":32,"nickname":"Second","seed":2,"points":18},'
        '{"user_id":33,"nickname":"Third","seed":3,"points":16},'
        '{"user_id":34,"nickname":"Fourth","seed":4,"points":11}'
        '],"matches":[{"group_number":1,"match_number":1,"state":"finished","winner_user_id":31}]}'
        ']'
    )

    modern_archive = SimpleNamespace(
        title="Modern cup",
        season="S2",
        winner_nickname="Winner",
        created_at=datetime(2024, 1, 1),
        bracket_payload_json=modern_payload,
    )

    fake_db = _FakeArchiveDB([], [modern_archive])

    async def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/archive")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert "archive-tree-participant-promoted" in response.text
    assert "archive-tree-participant-eliminated" in response.text
    assert "archive-tree-participant-gold" in response.text
    assert "archive-tree-participant-silver" in response.text
    assert "archive-tree-participant-bronze" in response.text

    final_stage_idx = response.text.index("archive-tree-stage-stage_final")
    gold_idx = response.text.index("archive-tree-participant-gold", final_stage_idx)
    silver_idx = response.text.index("archive-tree-participant-silver", final_stage_idx)
    bronze_idx = response.text.index("archive-tree-participant-bronze", final_stage_idx)

    assert response.text.index("Winner", final_stage_idx) > gold_idx
    assert response.text.index("Second", final_stage_idx) > silver_idx
    assert response.text.index("Third", final_stage_idx) > bronze_idx

    final_stage_slice = response.text[final_stage_idx:]
    assert final_stage_slice.count("archive-tree-participant-gold") == 1
    assert final_stage_slice.count("archive-tree-participant-silver") == 1
    assert final_stage_slice.count("archive-tree-participant-bronze") == 1
    assert "archive-tree-participant-purple" not in final_stage_slice
