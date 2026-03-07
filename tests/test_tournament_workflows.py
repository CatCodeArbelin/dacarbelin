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
    get_playoff_stage_sequence_keys,
    get_public_stage_display_sequence,
    parse_manual_draw_user_ids,
)
from app.services.tournament_view import build_bracket_columns, build_tournament_tree_vm, resolve_current_stage_label


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


    def test_stage_2_players_formed_for_48_profile(self) -> None:
        promoted = list(range(1, 25))
        direct_invites = list(range(101, 109))

        stage_2_player_ids = build_stage_2_player_ids(
            promoted,
            direct_invites,
            promoted_target_count=24,
            stage_2_size=32,
        )

        self.assertEqual(len(stage_2_player_ids), 32)
        self.assertEqual(stage_2_player_ids[:24], promoted)
        self.assertEqual(stage_2_player_ids[24:], direct_invites)

    def test_stage_2_direct_invite_preview_for_48_profile(self) -> None:
        preview = build_stage_2_direct_invite_preview(
            list(range(101, 120)),
            promoted_count=24,
            stage_2_size=32,
        )

        self.assertEqual(len(preview), 8)
        self.assertEqual(preview[0], {"user_id": 101, "seed": 25, "group_number": 4})
        self.assertEqual(preview[-1], {"user_id": 108, "seed": 32, "group_number": 4})

    def test_stage_2_direct_invites_respect_selected_group(self) -> None:
        promoted = list(range(1, 22))
        direct_invites = [101, 102, 103]
        direct_invite_groups = {101: 1, 102: 2, 103: 4}

        stage_2_player_ids = build_stage_2_player_ids(
            promoted,
            [*direct_invites, *list(range(104, 112))],
            direct_invite_groups=direct_invite_groups,
        )

        seed_by_user = {user_id: seed for seed, user_id in enumerate(stage_2_player_ids, start=1)}
        self.assertEqual(get_stage_group_number_by_seed(seed_by_user[101]), 1)
        self.assertEqual(get_stage_group_number_by_seed(seed_by_user[102]), 2)
        self.assertEqual(get_stage_group_number_by_seed(seed_by_user[103]), 4)

    def test_stage_2_preview_respect_selected_group(self) -> None:
        preview = build_stage_2_direct_invite_preview(
            [101, 102, 103],
            direct_invite_groups={101: 1, 102: 2, 103: 4},
        )

        self.assertEqual(preview[0]["group_number"], 1)
        self.assertEqual(preview[1]["group_number"], 2)
        self.assertEqual(preview[2]["group_number"], 4)

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


    def test_get_default_playoff_stage_key_prefers_first_stage_in_progression(self) -> None:
        stages = [
            SimpleNamespace(key="stage_2", is_started=False),
            SimpleNamespace(key="stage_1_4", is_started=False),
            SimpleNamespace(key="stage_final", is_started=False),
        ]

        stage_key = web.get_default_playoff_stage_key(stages, web.PLAYOFF_STAGE_KEYS_ORDER)

        self.assertEqual(stage_key, "stage_2")

    def test_get_default_playoff_stage_key_falls_back_to_first_known_stage(self) -> None:
        stages = [
            SimpleNamespace(key="custom_stage", is_started=False),
            SimpleNamespace(key="stage_final", is_started=False),
        ]

        stage_key = web.get_default_playoff_stage_key(stages, ["stage_2", "stage_1_4"])

        self.assertEqual(stage_key, "custom_stage")


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


def test_tournament_page_shows_tree_structure_before_start(monkeypatch) -> None:

    fake_db = _FakeTournamentPageDB()

    async def override_get_db():
        yield fake_db

    async def fake_get_draw_applied(db):
        return True

    async def fake_get_tournament_started(db):
        return False

    called = {"playoff_loaded": False}

    async def fake_get_playoff_stages_with_data(db):
        called["playoff_loaded"] = True
        return []

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
    assert "Сетка турнира" in response.text
    assert "Group A" in response.text
    assert "Group Final" in response.text
    assert called["playoff_loaded"] is True




def test_tournament_page_context_contains_expected_keys_when_started(monkeypatch) -> None:
    fake_db = _FakeTournamentPageDB()

    class _CaptureResponse:
        def __init__(self, context):
            self.context = context

    async def fake_get_tournament_started(db):
        return True

    async def fake_get_playoff_stages_with_data(db):
        return [SimpleNamespace(key="stage_2", is_started=True)]

    def fake_build_bracket_columns(groups, playoff_stages, user_by_id, direct_invite_ids, *args, **kwargs):
        return [{"key": "group_stage"}, {"key": "stage_2"}]

    def fake_build_tournament_tree_vm(groups, playoff_stages, user_by_id, direct_invite_ids, tournament_winner_user_id=None, *args, **kwargs):
        return {"stages": [{"key": "group_stage", "title": "I этап", "level": 0, "matches": []}]}

    def fake_template_response(request, template_name, context):
        return _CaptureResponse(context)

    monkeypatch.setattr(web, "get_tournament_started", fake_get_tournament_started)
    monkeypatch.setattr(web, "get_playoff_stages_with_data", fake_get_playoff_stages_with_data)
    monkeypatch.setattr(web, "build_bracket_columns", fake_build_bracket_columns)
    monkeypatch.setattr(web, "build_tournament_tree_vm", fake_build_tournament_tree_vm)
    monkeypatch.setattr(web.templates, "TemplateResponse", fake_template_response)

    request = SimpleNamespace(cookies={})
    response = __import__("asyncio").run(web.tournament_page(request, fake_db))

    assert response.context["playoff_stages"][0].key == "stage_2"
    assert response.context["stage_columns"] == [{"key": "group_stage"}, {"key": "stage_2"}]
    assert response.context["tournament_tree"]["stages"][0]["key"] == "group_stage"

def test_stage_order_constants_match_active_stage_progression_order() -> None:
    assert web.TOURNAMENT_STAGE_KEYS_ORDER == get_public_stage_display_sequence()
    assert web.PLAYOFF_STAGE_KEYS_ORDER == get_playoff_stage_sequence_keys()


def test_stage_display_order_rotates_active_stage_first() -> None:
    keys = get_public_stage_display_sequence()
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




def test_build_bracket_columns_sorts_stage_2_participants_by_points_within_group() -> None:
    stage = SimpleNamespace(
        key="stage_2",
        stage_size=32,
        participants=[
            SimpleNamespace(user_id=30, seed=1, points=10, wins=1, top4_finishes=1, top8_finishes=1, last_place=2),
            SimpleNamespace(user_id=20, seed=2, points=12, wins=0, top4_finishes=1, top8_finishes=1, last_place=3),
            SimpleNamespace(user_id=10, seed=8, points=12, wins=0, top4_finishes=1, top8_finishes=1, last_place=3),
        ],
        matches=[
            SimpleNamespace(group_number=1, game_number=1, schedule_text="TBD", lobby_password="0000", state="pending"),
        ],
    )

    columns = build_bracket_columns(
        groups=[],
        playoff_stages=[stage],
        user_by_id={},
        direct_invite_ids=[],
    )

    stage_2_column = next(column for column in columns if column["key"] == "stage_2")
    group_a = next(match for match in stage_2_column["matches"] if match["group_label"] == "A")

    assert [participant["user_id"] for participant in group_a["participants"]] == [10, 20, 30]



def test_build_bracket_columns_supports_legacy_stage_key_alias_for_stage_2() -> None:
    legacy_stage = SimpleNamespace(
        key="stage_1_8",
        stage_size=32,
        participants=[
            SimpleNamespace(user_id=501, seed=9, points=11, wins=1, top4_finishes=1, top8_finishes=1, last_place=2),
        ],
        matches=[
            SimpleNamespace(group_number=2, game_number=2, schedule_text="Tomorrow", lobby_password="1234", state="started"),
        ],
    )

    columns = build_bracket_columns(
        groups=[],
        playoff_stages=[legacy_stage],
        user_by_id={},
        direct_invite_ids=[],
    )

    stage_2_column = next(column for column in columns if column["key"] == "stage_2")
    group_b = next(match for match in stage_2_column["matches"] if match["group_label"] == "B")

    assert group_b["participants"]
    assert group_b["participants"][0]["user_id"] == 501
    assert group_b["state"] == "started"


def test_resolve_current_stage_label_normalizes_legacy_stage_aliases() -> None:
    legacy_stage = SimpleNamespace(key="stage4", title="Legacy Final", is_started=True)

    assert resolve_current_stage_label("ru", [legacy_stage], show_playoff=True) == "Финал (8, правило 22+победа)"
def test_build_bracket_columns_empty_tournament_has_all_stages_and_placeholders() -> None:
    columns = build_bracket_columns(
        groups=[],
        playoff_stages=[],
        user_by_id={},
        direct_invite_ids=[],
    )

    assert [column["key"] for column in columns] == ["group_stage", "stage_2", "stage_1_4", "stage_final"]

    group_stage = next(column for column in columns if column["key"] == "group_stage")
    assert [match["group_label"] for match in group_stage["matches"]] == ["A", "B", "C", "D", "E", "F", "G"]
    assert all(match["participants"] == [] for match in group_stage["matches"])
    assert all(match["game_number"] == 1 for match in group_stage["matches"])
    assert all(match["schedule_text"] == "TBD" for match in group_stage["matches"])
    assert all(match["state"] == "pending" for match in group_stage["matches"])

    stage_2 = next(column for column in columns if column["key"] == "stage_2")
    assert [match["group_label"] for match in stage_2["matches"]] == ["A", "B", "C", "D"]

    stage_1_4 = next(column for column in columns if column["key"] == "stage_1_4")
    assert [match["group_label"] for match in stage_1_4["matches"]] == ["A", "B"]

    stage_final = next(column for column in columns if column["key"] == "stage_final")
    assert len(stage_final["matches"]) == 1
    assert stage_final["matches"][0]["group_label"] == "Final"
    assert stage_final["matches"][0]["participants"] == []


def test_stage_2_preview_without_stage_and_invites_returns_four_empty_groups() -> None:
    columns = build_bracket_columns(
        groups=[],
        playoff_stages=[],
        user_by_id={},
        direct_invite_ids=[],
    )

    stage_2_column = next(column for column in columns if column["key"] == "stage_2")
    assert [match["group_label"] for match in stage_2_column["matches"]] == ["A", "B", "C", "D"]
    assert all(match["participants"] == [] for match in stage_2_column["matches"])
    assert all(match.get("is_preview") is True for match in stage_2_column["matches"])


def test_stage_2_preview_without_stage_keeps_four_groups_with_partial_invites() -> None:
    direct_invite_ids = [101, 102, 103]
    user_by_id = {
        101: SimpleNamespace(id=101, nickname="Alpha", game_nickname=""),
        102: SimpleNamespace(id=102, nickname="Bravo", game_nickname=""),
        103: SimpleNamespace(id=103, nickname="Charlie", game_nickname=""),
    }

    columns = build_bracket_columns(
        groups=[],
        playoff_stages=[],
        user_by_id=user_by_id,
        direct_invite_ids=direct_invite_ids,
    )

    stage_2_column = next(column for column in columns if column["key"] == "stage_2")
    assert [match["group_label"] for match in stage_2_column["matches"]] == ["A", "B", "C", "D"]
    participants_by_group = {match["group_label"]: match["participants"] for match in stage_2_column["matches"]}

    expected_by_group: dict[str, list[dict[str, object]]] = {"A": [], "B": [], "C": [], "D": []}
    for invited in build_stage_2_direct_invite_preview(direct_invite_ids):
        group_label = web.get_stage_group_label("stage_2", invited["group_number"])
        user = user_by_id[invited["user_id"]]
        expected_by_group[group_label].append(
            {
                "user_id": invited["user_id"],
                "nickname": user.nickname,
                "is_direct_invite_preview": True,
            }
        )

    assert participants_by_group == expected_by_group


def test_tournament_page_renders_stage_cards_when_database_is_empty(monkeypatch) -> None:
    class _EmptyTournamentPageDB:
        async def scalars(self, statement):
            return _FakeScalarResult([])

    fake_db = _EmptyTournamentPageDB()

    async def override_get_db():
        yield fake_db

    async def fake_get_tournament_started(db):
        return False

    monkeypatch.setattr(web, "get_tournament_started", fake_get_tournament_started)

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/tournament")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert "I этап" in response.text
    assert "II этап (32)" in response.text
    assert "III этап — полуфинальные группы (16)" in response.text
    assert "Финал (8)" in response.text
    assert response.text.count("Group A") >= 3
    assert "Group G" in response.text
    assert "Group Final" in response.text

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

    async def fake_validate_group_draw_integrity(db, **kwargs):
        return True, None

    async def fake_apply_game_results(db, group_id: int, ordered_user_ids: list[int]):
        state["apply_game_results_called"] = True
        assert group_id == 1
        assert ordered_user_ids == [101, 102, 103, 104, 105, 106, 107, 108]

    async def fake_generate_playoff_from_groups(db):
        return True, "ok"

    async def fake_get_current_tournament_profile_key(db):
        return "56"

    async def fake_scalar(self, statement):
        sql = str(statement)
        if "count(tournament_groups.id)" in sql:
            return state["groups_count"]
        if "FROM site_settings" in sql:
            if not hasattr(fake_scalar, "_site_setting_calls"):
                fake_scalar._site_setting_calls = 0
            fake_scalar._site_setting_calls += 1
            if fake_scalar._site_setting_calls == 1:
                return tournament_started_setting
            return registration_open_setting
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
    monkeypatch.setattr(web, "get_current_tournament_profile_key", fake_get_current_tournament_profile_key)
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


def test_stage_sequences_are_identical_between_service_view_and_web() -> None:
    playoff_keys = get_playoff_stage_sequence_keys()
    assert playoff_keys == [stage[0] for stage in get_playoff_stage_blueprint(32)]

    columns = build_bracket_columns(groups=[], playoff_stages=[], user_by_id={}, direct_invite_ids=[])
    assert [column["key"] for column in columns] == get_public_stage_display_sequence()

    ordered_keys = web.build_stage_display_order("group_stage", get_public_stage_display_sequence())
    assert ordered_keys == get_public_stage_display_sequence()


def test_admin_progression_uses_service_playoff_stage_sequence() -> None:
    assert get_playoff_stage_sequence_keys() == ["stage_2", "stage_1_4", "stage_final"]

def test_build_tournament_tree_vm_has_stages_before_start() -> None:
    tree = build_tournament_tree_vm(
        groups=[],
        playoff_stages=[],
        user_by_id={},
        direct_invite_ids=[],
    )

    assert [stage["key"] for stage in tree["stages"]] == ["group_stage", "stage_2", "stage_1_4", "stage_final"]
    assert tree["stages"][0]["matches"]


def test_build_tournament_tree_vm_marks_final_winner() -> None:
    stage_final = SimpleNamespace(
        key="stage_final",
        stage_size=8,
        participants=[
            SimpleNamespace(user_id=1, seed=1, points=24, wins=1, top4_finishes=1, top8_finishes=1, last_place=2),
            SimpleNamespace(user_id=2, seed=2, points=20, wins=0, top4_finishes=1, top8_finishes=1, last_place=4),
        ],
        matches=[
            SimpleNamespace(
                group_number=1,
                game_number=1,
                schedule_text="today",
                lobby_password="pw",
                state="finished",
                winner_user_id=1,
                manual_winner_user_id=None,
            )
        ],
    )
    tree = build_tournament_tree_vm(
        groups=[],
        playoff_stages=[stage_final],
        user_by_id={},
        direct_invite_ids=[],
    )

    final_stage = next(stage for stage in tree["stages"] if stage["key"] == "stage_final")
    winner_rows = [p for p in final_stage["matches"][0]["participants"] if p.get("is_tournament_winner")]
    assert len(winner_rows) == 1
    assert winner_rows[0]["user_id"] == 1
    assert winner_rows[0]["highlight_color"] == "gold"


def test_build_tournament_tree_vm_prefers_manual_final_winner() -> None:
    stage_final = SimpleNamespace(
        key="stage_final",
        stage_size=8,
        participants=[
            SimpleNamespace(user_id=1, seed=1, points=24, wins=1, top4_finishes=1, top8_finishes=1, last_place=2),
            SimpleNamespace(user_id=2, seed=2, points=20, wins=0, top4_finishes=1, top8_finishes=1, last_place=4),
            SimpleNamespace(user_id=3, seed=3, points=18, wins=0, top4_finishes=1, top8_finishes=1, last_place=5),
        ],
        matches=[
            SimpleNamespace(
                group_number=1,
                game_number=1,
                schedule_text="today",
                lobby_password="pw",
                state="finished",
                winner_user_id=1,
                manual_winner_user_id=2,
            )
        ],
    )
    tree = build_tournament_tree_vm(
        groups=[],
        playoff_stages=[stage_final],
        user_by_id={},
        direct_invite_ids=[],
    )

    final_stage = next(stage for stage in tree["stages"] if stage["key"] == "stage_final")
    participants = final_stage["matches"][0]["participants"]
    winner = next(p for p in participants if p.get("is_tournament_winner"))
    assert winner["user_id"] == 2
    assert winner["highlight_color"] == "gold"


def test_build_tournament_tree_vm_stage_order_is_stable() -> None:
    tree = build_tournament_tree_vm(
        groups=[],
        playoff_stages=[SimpleNamespace(key="stage_2", stage_size=32, participants=[], matches=[])],
        user_by_id={},
        direct_invite_ids=[],
    )

    assert [(stage["level"], stage["key"]) for stage in tree["stages"]] == [
        (0, "group_stage"),
        (1, "stage_2"),
        (2, "stage_1_4"),
        (3, "stage_final"),
    ]
