"""Проверяет ключевые workflow-сценарии управления турниром."""

import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.admin_session import ADMIN_SESSION_COOKIE, create_admin_session_cookie
from app.db.session import get_db
from app.main import app
from app.routers import web
from app.services.tournament import (
    build_stage_2_player_ids,
    build_stage_2_direct_invite_preview,
    get_stage_group_number_by_seed,
    get_group_count_for_stage,
    get_playoff_stage_blueprint,
    parse_manual_draw_user_ids,
)
from app.services.tournament_view import build_bracket_columns, resolve_current_stage_label


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
        stages_32 = get_playoff_stage_blueprint(32)
        self.assertEqual(
            [stage[0] for stage in stages_32],
            [
                "stage_2",
                "stage_1_4",
                "stage_final",
            ],
        )
        self.assertEqual([stage[2] for stage in stages_32], [32, 16, 8])
        self.assertEqual([stage[3] for stage in stages_32], ["standard", "standard", "final_22_top1"])

        stages_16 = get_playoff_stage_blueprint(16)
        self.assertEqual(stages_16, [])

    def test_stage_group_counts_for_new_playoff_flow(self) -> None:
        """Проверяет граничный сценарий `test_stage_group_counts_for_new_playoff_flow`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_workflows.py -q` и `pytest tests/test_tournament_workflows.py -k "test_stage_group_counts_for_new_playoff_flow" -q`."""
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


    def test_stage_2_direct_invite_preview_uses_stage_seeding(self) -> None:
        """Проверяет позитивный сценарий `test_stage_2_direct_invite_preview_uses_stage_seeding`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_workflows.py -q` и `pytest tests/test_tournament_workflows.py -k "test_stage_2_direct_invite_preview_uses_stage_seeding" -q`."""
        preview = build_stage_2_direct_invite_preview(list(range(101, 115)))

        self.assertEqual(len(preview), 11)
        self.assertEqual(preview[0], {"user_id": 101, "seed": 22, "group_number": 3})
        self.assertEqual(preview[-1], {"user_id": 111, "seed": 32, "group_number": 4})

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

    def test_resolve_current_stage_label_returns_uniform_display_for_all_stages(self) -> None:
        """Проверяет позитивный сценарий `test_resolve_current_stage_label_returns_uniform_display_for_all_stages`."""
        stage_cases = [
            ("group_stage", "tournament_stage_group_stage_label"),
            ("stage_2", "tournament_stage_1_4_label"),
            ("stage_1_8", "tournament_stage_1_8_label"),
            ("stage_1_4", "tournament_stage_semifinal_groups_label"),
            ("stage_final", "tournament_stage_final_label"),
        ]

        for stage_key, expected_key in stage_cases:
            stage = SimpleNamespace(key=stage_key, is_started=True, title=f"title:{stage_key}")
            self.assertEqual(resolve_current_stage_label("en", [stage], show_playoff=True), web.t("en", expected_key))

    def test_resolve_current_stage_label_fallback_uses_stage_title_for_unknown_key(self) -> None:
        """Проверяет граничный сценарий `test_resolve_current_stage_label_fallback_uses_stage_title_for_unknown_key`."""
        unknown_stage = SimpleNamespace(key="unknown", is_started=True, title="Custom Stage")
        self.assertEqual(resolve_current_stage_label("en", [unknown_stage], show_playoff=True), "Custom Stage")


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeTournamentGroup:
    id = 1
    name = "A"
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




def test_tournament_page_context_contains_expected_keys_when_started(monkeypatch) -> None:
    fake_db = _FakeTournamentPageDB()

    class _CaptureResponse:
        def __init__(self, context):
            self.context = context

    async def fake_get_tournament_started(db):
        return True

    async def fake_get_playoff_stages_with_data(db):
        return [SimpleNamespace(key="stage_2", is_started=True)]

    def fake_build_bracket_columns(groups, playoff_stages, user_by_id, direct_invite_ids):
        return [{"key": "group_stage"}, {"key": "stage_2"}]

    def fake_build_playoff_standings(playoff_stages, user_by_id):
        return [{"stage_key": "stage_2", "rows": []}]

    def fake_template_response(request, template_name, context):
        return _CaptureResponse(context)

    monkeypatch.setattr(web, "get_tournament_started", fake_get_tournament_started)
    monkeypatch.setattr(web, "get_playoff_stages_with_data", fake_get_playoff_stages_with_data)
    monkeypatch.setattr(web, "build_bracket_columns", fake_build_bracket_columns)
    monkeypatch.setattr(web, "build_playoff_standings", fake_build_playoff_standings)
    monkeypatch.setattr(web.templates, "TemplateResponse", fake_template_response)

    request = SimpleNamespace(cookies={})
    response = __import__("asyncio").run(web.tournament_page(request, fake_db))

    assert response.context["show_groups"] is True
    assert response.context["playoff_stages"][0].key == "stage_2"
    assert response.context["stage_columns"] == [{"key": "group_stage"}, {"key": "stage_2"}]
    assert response.context["ordered_stage_columns"] == [{"key": "stage_2"}, {"key": "group_stage"}]
    assert response.context["playoff_standings"] == [{"stage_key": "stage_2", "rows": []}]

def test_stage_display_order_rotates_active_stage_first() -> None:
    keys = ["group_stage", "stage_2", "stage_1_4", "stage_final"]
    assert web.build_stage_display_order("group_stage", keys) == ["group_stage", "stage_2", "stage_1_4", "stage_final"]
    assert web.build_stage_display_order("stage_2", keys) == ["stage_2", "stage_1_4", "stage_final", "group_stage"]
    assert web.build_stage_display_order("stage_final", keys) == ["stage_final", "stage_1_4", "stage_2", "group_stage"]


def test_get_stage_group_numbers_limits_stage_2_to_real_groups() -> None:
    assert web.get_stage_group_numbers("stage_2") == [1, 2, 3, 4]
    assert web.get_stage_group_numbers("stage_2", stage_size=32, participants_count=32) == [1, 2, 3, 4]
    assert web.get_stage_group_numbers("stage_2", stage_size=32, participants_count=26) == [1, 2, 3, 4]
    assert web.get_stage_group_numbers("stage_2", stage_size=32, participants_count=24) == [1, 2, 3, 4]


def test_build_bracket_columns_adds_placeholders_for_missing_stage_groups() -> None:
    stage = SimpleNamespace(
        key="stage_2",
        stage_size=32,
        participants=[],
        matches=[],
    )

    columns = build_bracket_columns(
        groups=[],
        playoff_stages=[stage],
        user_by_id={},
        direct_invite_ids=[],
    )

    stage_2_column = next(column for column in columns if column["key"] == "stage_2")
    assert [match["group_label"] for match in stage_2_column["matches"]] == ["A", "B", "C", "D"]
    assert all(match["game_number"] == 1 for match in stage_2_column["matches"])
    assert all(match["schedule_text"] == "TBD" for match in stage_2_column["matches"])
    assert all(match["lobby_password"] == "TBD" for match in stage_2_column["matches"])
    assert all(match["participants"] == [] for match in stage_2_column["matches"])
    assert all(match["state"] == "pending" for match in stage_2_column["matches"])

def test_deprecated_manual_playoff_routes_redirect_to_group_finish_flow() -> None:
    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response_start = client.post(
            "/admin/playoff/start",
            data={"stage_id": "1"},
            follow_redirects=False,
        )
        response_promote = client.post(
            "/admin/playoff/promote",
            data={"stage_id": "1", "top_n": "4"},
            follow_redirects=False,
        )
        response_generate = client.post(
            "/admin/playoff/generate",
            follow_redirects=False,
        )

    assert response_start.status_code == 303
    assert "details=use_group_finish_flow" in response_start.headers["location"]
    assert response_promote.status_code == 303
    assert "details=use_group_finish_flow" in response_promote.headers["location"]
    assert response_generate.status_code == 303
    assert "details=use_group_finish_flow" in response_generate.headers["location"]


if __name__ == "__main__":
    unittest.main()


def test_admin_auto_apply_start_then_group_score_flow(monkeypatch) -> None:
    """E2E-like сценарий: auto draw → apply → start → ввод результатов группы."""
    state: dict[str, object] = {
        "draw_applied": False,
        "groups_count": 8,
        "tournament_started": "0",
        "registration_open": "1",
        "set_draw_applied_calls": [],
        "apply_game_results_called": False,
    }

    class _FakeSetting:
        def __init__(self, key: str, value: str) -> None:
            self.key = key
            self.value = value

    tournament_started_setting = _FakeSetting("tournament_started", "0")
    registration_open_setting = _FakeSetting("registration_open", "1")

    async def fake_create_auto_draw(db):
        return True, "ok"

    async def fake_set_draw_applied(db, value: bool):
        state["draw_applied"] = value
        cast_calls = state["set_draw_applied_calls"]
        assert isinstance(cast_calls, list)
        cast_calls.append(value)

    async def fake_get_draw_applied(db):
        return bool(state["draw_applied"])

    async def fake_validate_group_draw_integrity(db):
        return True, None

    async def fake_apply_game_results(db, group_id: int, ordered_user_ids: list[int]):
        state["apply_game_results_called"] = True
        assert group_id == 1
        assert ordered_user_ids == [101, 102, 103, 104, 105, 106, 107, 108]

    async def fake_generate_playoff_from_groups(db):
        return True, "ok"

    async def fake_scalar(self, statement):
        sql = str(statement)
        if "count(tournament_groups.id)" in sql:
            return state["groups_count"]
        if "FROM site_settings" in sql:
            if not hasattr(fake_scalar, "_setting_calls"):
                fake_scalar._setting_calls = 0
            fake_scalar._setting_calls += 1
            return tournament_started_setting if fake_scalar._setting_calls == 1 else registration_open_setting
        return None

    async def fake_commit(self):
        state["tournament_started"] = tournament_started_setting.value
        state["registration_open"] = registration_open_setting.value
        return None

    def fake_add(self, obj):
        return None

    monkeypatch.setattr(web, "create_auto_draw", fake_create_auto_draw)
    monkeypatch.setattr(web, "set_draw_applied", fake_set_draw_applied)
    monkeypatch.setattr(web, "get_draw_applied", fake_get_draw_applied)
    monkeypatch.setattr(web, "validate_group_draw_integrity", fake_validate_group_draw_integrity)
    monkeypatch.setattr(web, "apply_game_results", fake_apply_game_results)
    monkeypatch.setattr(web, "generate_playoff_from_groups", fake_generate_playoff_from_groups)
    monkeypatch.setattr(web.AsyncSession, "scalar", fake_scalar, raising=False)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)
    monkeypatch.setattr(web.AsyncSession, "add", fake_add, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())

        response_auto = client.post("/admin/draw/auto", follow_redirects=False)
        response_apply = client.post("/admin/draw/apply", follow_redirects=False)
        response_start = client.post("/admin/tournament/start", follow_redirects=False)
        response_score = client.post(
            "/admin/group/score",
            data={
                "group_id": "1",
                "user_ids[]": ["101", "102", "103", "104", "105", "106", "107", "108"],
                "places[]": ["1", "2", "3", "4", "5", "6", "7", "8"],
            },
            follow_redirects=False,
        )

    assert response_auto.status_code == 303
    assert response_auto.headers["location"] == "/admin?msg=msg_status_ok"

    assert response_apply.status_code == 303
    assert response_apply.headers["location"] == "/admin?msg=msg_status_ok&details=draw_applied_groups%3A8"

    assert response_start.status_code == 303
    assert response_start.headers["location"] == "/admin?msg=msg_status_ok"

    assert response_score.status_code == 303
    assert response_score.headers["location"] == "/admin?msg=msg_game_saved"

    assert state["set_draw_applied_calls"] == [False, True]
    assert state["apply_game_results_called"] is True
    assert tournament_started_setting.value == "1"
    assert registration_open_setting.value == "0"
