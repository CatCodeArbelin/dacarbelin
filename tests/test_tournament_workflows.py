"""Проверяет ключевые workflow-сценарии управления турниром."""

import unittest

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.routers import web
from app.services.tournament import (
    build_stage_2_player_ids,
    get_stage_group_number_by_seed,
    get_group_count_for_stage,
    get_playoff_stage_blueprint,
    parse_manual_draw_user_ids,
)


class TournamentWorkflowTests(unittest.TestCase):
    def test_parse_manual_draw_user_ids(self) -> None:
        """Проверяет позитивный сценарий `test_parse_manual_draw_user_ids`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_workflows.py -q` и `pytest tests/test_tournament_workflows.py -k "test_parse_manual_draw_user_ids" -q`."""
        self.assertEqual(parse_manual_draw_user_ids("1, 2,3"), [1, 2, 3])
        self.assertEqual(parse_manual_draw_user_ids(["4", " 5 ", "6"]), [4, 5, 6])
        self.assertEqual(parse_manual_draw_user_ids(""), [])
        self.assertEqual(parse_manual_draw_user_ids([]), [])
        with self.assertRaises(ValueError):
            parse_manual_draw_user_ids("7,7")

    def test_parse_manual_draw_user_ids_invalid_inputs(self) -> None:
        """Проверяет негативный сценарий `test_parse_manual_draw_user_ids_invalid_inputs`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_workflows.py -q` и `pytest tests/test_tournament_workflows.py -k "test_parse_manual_draw_user_ids_invalid_inputs" -q`."""
        with self.assertRaises(ValueError) as none_ctx:
            parse_manual_draw_user_ids(None)
        self.assertEqual(str(none_ctx.exception), "Список ID участников обязателен")

        with self.assertRaises(ValueError) as letters_ctx:
            parse_manual_draw_user_ids("1,a,3")
        self.assertEqual(str(letters_ctx.exception), "ID участников должны быть целыми числами")

        with self.assertRaises(ValueError) as mixed_ctx:
            parse_manual_draw_user_ids(["10", "x", 12])
        self.assertEqual(str(mixed_ctx.exception), "ID участников должны быть целыми числами")

    def test_playoff_stage_blueprint(self) -> None:
        """Проверяет позитивный сценарий `test_playoff_stage_blueprint`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_workflows.py -q` и `pytest tests/test_tournament_workflows.py -k "test_playoff_stage_blueprint" -q`."""
        stages_56 = get_playoff_stage_blueprint(56)
        self.assertEqual(
            [stage[0] for stage in stages_56],
            [
                "stage_1_8",
                "stage_1_4",
                "stage_semifinal_groups",
                "stage_final",
            ],
        )
        self.assertEqual([stage[2] for stage in stages_56], [56, 32, 16, 8])
        self.assertEqual([stage[3] for stage in stages_56], ["standard", "standard", "standard", "final_22_top1"])

        stages_32 = get_playoff_stage_blueprint(32)
        self.assertEqual(
            [stage[0] for stage in stages_32],
            [
                "stage_1_4",
                "stage_semifinal_groups",
                "stage_final",
            ],
        )
        self.assertEqual([stage[2] for stage in stages_32], [32, 16, 8])

    def test_stage_group_counts_for_new_playoff_flow(self) -> None:
        """Проверяет граничный сценарий `test_stage_group_counts_for_new_playoff_flow`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_workflows.py -q` и `pytest tests/test_tournament_workflows.py -k "test_stage_group_counts_for_new_playoff_flow" -q`."""
        self.assertEqual(get_group_count_for_stage(56), 7)
        self.assertEqual(get_group_count_for_stage(32), 4)
        self.assertEqual(get_group_count_for_stage(16), 2)
        self.assertEqual(get_group_count_for_stage(8), 1)

    def test_stage_2_players_formed_as_21_plus_11(self) -> None:
        """Проверяет граничный сценарий `test_stage_2_players_formed_as_21_plus_11`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_workflows.py -q` и `pytest tests/test_tournament_workflows.py -k "test_stage_2_players_formed_as_21_plus_11" -q`."""
        promoted = list(range(1, 22))
        direct_invites = list(range(101, 112))

        stage_2_player_ids = build_stage_2_player_ids(promoted, direct_invites)

        self.assertEqual(len(stage_2_player_ids), 32)
        self.assertEqual(stage_2_player_ids[:21], promoted)
        self.assertEqual(stage_2_player_ids[21:], direct_invites)
        self.assertEqual(get_group_count_for_stage(len(stage_2_player_ids)), 4)

        group_sizes: dict[int, int] = {}
        for seed in range(1, len(stage_2_player_ids) + 1):
            group_number = get_stage_group_number_by_seed(seed)
            group_sizes[group_number] = group_sizes.get(group_number, 0) + 1
        self.assertEqual(group_sizes, {1: 8, 2: 8, 3: 8, 4: 8})

    def test_stage_2_players_requires_exactly_21_promoted(self) -> None:
        """Проверяет негативный сценарий `test_stage_2_players_requires_exactly_21_promoted`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_workflows.py -q` и `pytest tests/test_tournament_workflows.py -k "test_stage_2_players_requires_exactly_21_promoted" -q`."""
        with self.assertRaises(ValueError):
            build_stage_2_player_ids(list(range(1, 21)), list(range(101, 112)))

        with self.assertRaises(ValueError):
            build_stage_2_player_ids(list(range(1, 23)), list(range(101, 112)))

    def test_stage_2_players_validation_for_limit_and_duplicates(self) -> None:
        """Проверяет негативный сценарий `test_stage_2_players_validation_for_limit_and_duplicates`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_workflows.py -q` и `pytest tests/test_tournament_workflows.py -k "test_stage_2_players_validation_for_limit_and_duplicates" -q`."""
        promoted = list(range(1, 22))

        with self.assertRaises(ValueError):
            build_stage_2_player_ids(promoted, list(range(101, 113)))

        with self.assertRaises(ValueError):
            build_stage_2_player_ids(promoted, [21, *range(101, 111)])


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeTournamentGroup:
    id = 1
    members = []


class _FakeTournamentPageDB:
    def __init__(self) -> None:
        self._calls = 0

    async def scalars(self, statement):
        self._calls += 1
        if self._calls == 1:
            return _FakeScalarResult([_FakeTournamentGroup()])
        return _FakeScalarResult([])


def test_tournament_page_hides_groups_before_start(monkeypatch) -> None:
    """Проверяет негативный сценарий `test_tournament_page_hides_groups_before_start`.
    Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
    Запуск: `pytest tests/test_tournament_workflows.py -q` и `pytest tests/test_tournament_workflows.py -k "test_tournament_page_hides_groups_before_start" -q`."""

    fake_db = _FakeTournamentPageDB()

    async def override_get_db():
        yield fake_db

    async def fake_get_draw_applied(db):
        return True

    async def fake_get_tournament_started(db):
        return False

    async def fake_get_playoff_stages_with_data(db):
        raise AssertionError("Playoff data must stay hidden before tournament start")

    monkeypatch.setattr(web, "get_draw_applied", fake_get_draw_applied)
    monkeypatch.setattr(web, "get_tournament_started", fake_get_tournament_started)
    monkeypatch.setattr(web, "get_playoff_stages_with_data", fake_get_playoff_stages_with_data)

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/tournament")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert "Groups are prepared and will be shown after tournament start" in response.text
    assert "tournament_group_stage_title" not in response.text
    assert "Current playoff stage / bracket" not in response.text


if __name__ == "__main__":
    unittest.main()
