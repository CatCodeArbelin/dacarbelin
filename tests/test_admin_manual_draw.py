"""Проверяет ручную жеребьевку через admin API с выбором участников из формы."""
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.core.admin_session import ADMIN_SESSION_COOKIE, create_admin_session_cookie
from app.main import app
from app.routers import web


def test_admin_manual_draw_accepts_user_ids_array(monkeypatch) -> None:
    """Проверяет позитивный сценарий `test_admin_manual_draw_accepts_user_ids_array`.
    Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
    Запуск: `pytest tests/test_admin_manual_draw.py -q` и `pytest tests/test_admin_manual_draw.py -k "test_admin_manual_draw_accepts_user_ids_array" -q`."""
    captured: dict[str, int | list[int]] = {}

    async def fake_create_manual_draw(db, group_count: int, user_ids: list[int]) -> None:
        captured["group_count"] = group_count
        captured["user_ids"] = user_ids

    async def fake_set_draw_applied(db, value: bool):
        return None

    async def fake_commit(self):
        return None

    monkeypatch.setattr(web, "create_manual_draw", fake_create_manual_draw)
    monkeypatch.setattr(web, "set_draw_applied", fake_set_draw_applied)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/draw/manual",
            data={"group_count": "2", "user_ids[]": ["11", "12"]},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_status_ok"
    assert captured == {"group_count": 2, "user_ids": [11, 12]}




def test_admin_manual_draw_accepts_layout_json(monkeypatch) -> None:
    """Проверяет ручную жеребьевку через layout_json."""
    captured: dict[str, list[list[int]]] = {}

    async def fake_create_manual_draw_from_layout(db, layout: list[list[int]]) -> None:
        captured["layout"] = layout

    async def fake_set_draw_applied(db, value: bool):
        return None

    async def fake_commit(self):
        return None

    monkeypatch.setattr(web, "create_manual_draw_from_layout", fake_create_manual_draw_from_layout)
    monkeypatch.setattr(web, "set_draw_applied", fake_set_draw_applied)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/draw/manual",
            data={"layout_json": '{"A": ["11", "12"], "B": ["13"]}'},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_status_ok"
    assert captured == {"layout": [["11", "12"], ["13"]]}


def test_admin_manual_draw_returns_validation_details_for_layout(monkeypatch) -> None:
    """Проверяет отдачу details при ошибках валидации layout_json."""

    async def fake_create_manual_draw_from_layout(db, layout: list[list[int]]) -> None:
        raise web.ManualDrawValidationError("duplicate_user:11")

    monkeypatch.setattr(web, "create_manual_draw_from_layout", fake_create_manual_draw_from_layout)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/draw/manual",
            data={"layout_json": '{"A": ["11", "11"]}'},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_operation_failed&details=duplicate_user%3A11"


def test_admin_manual_draw_returns_invalid_layout_for_bad_json() -> None:
    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/draw/manual",
            data={"layout_json": "{invalid-json"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_operation_failed&details=invalid_layout"

def test_admin_auto_draw_redirect_contains_details_on_error(monkeypatch) -> None:
    """Проверяет негативный сценарий `test_admin_auto_draw_redirect_contains_details_on_error`.
    Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
    Запуск: `pytest tests/test_admin_manual_draw.py -q` и `pytest tests/test_admin_manual_draw.py -k "test_admin_auto_draw_redirect_contains_details_on_error" -q`."""
    async def fake_create_auto_draw(db):
        return False, "Автожеребьевка недоступна: требуется минимум 56 валидных участников (формат 7x8)."

    monkeypatch.setattr(web, "create_auto_draw", fake_create_auto_draw)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post("/admin/draw/auto", follow_redirects=False)

    assert response.status_code == 303
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)

    assert parsed.path == "/admin"
    assert query["msg"] == ["msg_status_warn"]
    assert query["details"] == ["Автожеребьевка недоступна: требуется минимум 56 валидных участников (формат 7x8)."]


def test_admin_apply_draw_sets_draw_applied_flag(monkeypatch) -> None:
    """Проверяет позитивный сценарий применения жеребьевки и установки флага."""
    state: dict[str, bool] = {"committed": False, "set_true": False}

    async def fake_validate_group_draw_integrity(db):
        return True, None

    async def fake_set_draw_applied(db, value: bool):
        state["set_true"] = value

    async def fake_commit(self):
        state["committed"] = True

    async def fake_scalar(self, statement):
        if "count(tournament_groups.id)" in str(statement):
            return 8
        return None

    monkeypatch.setattr(web, "validate_group_draw_integrity", fake_validate_group_draw_integrity)
    monkeypatch.setattr(web, "set_draw_applied", fake_set_draw_applied)
    monkeypatch.setattr(web.AsyncSession, "scalar", fake_scalar, raising=False)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post("/admin/draw/apply", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_status_ok&details=draw_applied_groups%3A8"
    assert state == {"committed": True, "set_true": True}


def test_admin_start_tournament_requires_applied_draw(monkeypatch) -> None:
    """Проверяет guard на запуск турнира без применения жеребьевки."""

    async def fake_get_draw_applied(db):
        return False

    async def fake_scalar(self, statement):
        if "count(tournament_groups.id)" in str(statement):
            return 8
        return None

    monkeypatch.setattr(web, "get_draw_applied", fake_get_draw_applied)
    monkeypatch.setattr(web.AsyncSession, "scalar", fake_scalar, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post("/admin/tournament/start", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_operation_failed&details=draw_not_applied"


def test_admin_manual_draw_resets_draw_applied(monkeypatch) -> None:
    """Проверяет сброс флага draw_applied после ручной жеребьевки."""
    state: dict[str, bool] = {"set_false": False, "committed": False}

    async def fake_create_manual_draw(db, group_count: int, user_ids: list[int]) -> None:
        return None

    async def fake_set_draw_applied(db, value: bool):
        state["set_false"] = (value is False)

    async def fake_commit(self):
        state["committed"] = True

    monkeypatch.setattr(web, "create_manual_draw", fake_create_manual_draw)
    monkeypatch.setattr(web, "set_draw_applied", fake_set_draw_applied)
    monkeypatch.setattr(web.AsyncSession, "commit", fake_commit, raising=False)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post("/admin/draw/manual", data={"group_count": "2", "user_ids[]": ["11", "12"]}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_status_ok"
    assert state == {"set_false": True, "committed": True}


def test_admin_group_score_builds_ordered_user_ids_from_places(monkeypatch) -> None:
    """Проверяет, что admin/group/score сортирует участников по местам перед вызовом сервиса."""
    captured: dict[str, int | list[int]] = {}

    async def fake_apply_game_results(db, group_id: int, ordered_user_ids: list[int]) -> None:
        captured["group_id"] = group_id
        captured["ordered_user_ids"] = ordered_user_ids

    async def fake_generate_playoff_from_groups(db):
        return True, "ok"

    monkeypatch.setattr(web, "apply_game_results", fake_apply_game_results)
    monkeypatch.setattr(web, "generate_playoff_from_groups", fake_generate_playoff_from_groups)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/group/score",
            data={
                "group_id": "7",
                "user_ids[]": ["101", "102", "103", "104", "105", "106", "107", "108"],
                "places[]": ["2", "1", "3", "4", "5", "6", "7", "8"],
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_game_saved"
    assert captured == {"group_id": 7, "ordered_user_ids": [102, 101, 103, 104, 105, 106, 107, 108]}


def test_admin_group_score_rejects_duplicate_places() -> None:
    """Негативный кейс: повторяющееся место."""
    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/group/score",
            data={
                "group_id": "7",
                "user_ids[]": ["101", "102", "103", "104", "105", "106", "107", "108"],
                "places[]": ["1", "1", "3", "4", "5", "6", "7", "8"],
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_operation_failed"


def test_admin_group_score_rejects_not_all_places() -> None:
    """Негативный кейс: неполное покрытие диапазона мест 1..8."""
    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/group/score",
            data={
                "group_id": "7",
                "user_ids[]": ["101", "102", "103", "104", "105", "106", "107", "108"],
                "places[]": ["1", "2", "3", "4", "5", "6", "7", "7"],
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_operation_failed"


def test_admin_group_score_rejects_less_than_eight_participants() -> None:
    """Негативный кейс: передано меньше 8 участников."""
    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/group/score",
            data={
                "group_id": "7",
                "user_ids[]": ["101", "102", "103", "104", "105", "106", "107"],
                "places[]": ["1", "2", "3", "4", "5", "6", "7"],
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_operation_failed"


def test_admin_group_score_rejects_player_not_in_group(monkeypatch) -> None:
    """Негативный кейс: сервис отклоняет игрока, которого нет в группе."""

    async def fake_apply_game_results(db, group_id: int, ordered_user_ids: list[int]) -> None:
        raise ValueError("В результатах есть игрок, которого нет в группе")

    monkeypatch.setattr(web, "apply_game_results", fake_apply_game_results)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/group/score",
            data={
                "group_id": "7",
                "user_ids[]": ["101", "102", "103", "104", "105", "106", "107", "108"],
                "places[]": ["1", "2", "3", "4", "5", "6", "7", "8"],
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_operation_failed"


def test_admin_playoff_start_returns_friendly_error_for_invalid_stage(monkeypatch) -> None:
    """Негативный кейс: invalid stage_id для запуска стадии playoff."""

    async def fake_playoff_stage_exists(db, stage_id: int) -> bool:
        return False

    monkeypatch.setattr(web, "_playoff_stage_exists", fake_playoff_stage_exists)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post("/admin/playoff/start", data={"stage_id": "999"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_operation_failed&details=use_group_finish_flow"


def test_admin_playoff_move_returns_friendly_error_for_invalid_stage(monkeypatch) -> None:
    """Негативный кейс: invalid from/to stage_id для ручного переноса в playoff."""

    async def fake_playoff_stage_exists(db, stage_id: int) -> bool:
        return False

    monkeypatch.setattr(web, "_playoff_stage_exists", fake_playoff_stage_exists)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/playoff/move",
            data={"from_stage_id": "999", "to_stage_id": "998", "user_id": "11"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_invalid_playoff_stage"


def test_admin_group_promote_manual_returns_friendly_error_for_invalid_stage(monkeypatch) -> None:
    """Негативный кейс: invalid target_stage_id при ручном переводе из группы."""

    async def fake_playoff_stage_exists(db, stage_id: int) -> bool:
        return False

    monkeypatch.setattr(web, "_playoff_stage_exists", fake_playoff_stage_exists)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/group/promote-manual",
            data={"group_id": "1", "user_id": "11", "target_stage_id": "999"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_invalid_playoff_stage"



def test_admin_debug_simulate_three_games_returns_friendly_error_for_invalid_stage(monkeypatch) -> None:
    """Негативный кейс: invalid stage_id для debug-симуляции плей-офф."""

    async def fake_playoff_stage_exists(db, stage_id: int) -> bool:
        return False

    monkeypatch.setattr(web, "_playoff_stage_exists", fake_playoff_stage_exists)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/playoff/debug/simulate-3-games",
            data={"stage_id": "999"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_invalid_playoff_stage"


def test_admin_debug_simulate_three_games_uses_submitted_stage_id(monkeypatch) -> None:
    """Позитивный кейс: роут передает stage_id в сервис для симуляции конкретной стадии."""
    captured: dict[str, int] = {}

    async def fake_playoff_stage_exists(db, stage_id: int) -> bool:
        return True

    async def fake_simulate_three_random_games_for_stage(db, stage_id: int) -> None:
        captured["stage_id"] = stage_id

    monkeypatch.setattr(web, "_playoff_stage_exists", fake_playoff_stage_exists)
    monkeypatch.setattr(web, "simulate_three_random_games_for_stage", fake_simulate_three_random_games_for_stage)

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        response = client.post(
            "/admin/playoff/debug/simulate-3-games",
            data={"stage_id": "123"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin?msg=msg_status_ok&details=debug_simulate_3_games_done"
    assert captured == {"stage_id": 123}


def test_admin_manual_group_edit_routes_are_unavailable() -> None:
    """Проверяет, что удаленные ручные роуты редактирования групп недоступны."""
    routes = [
        "/admin/group/create",
        "/admin/group/member/add",
        "/admin/group/member/remove",
        "/admin/group/member/move",
        "/admin/group/member/swap",
    ]

    with TestClient(app) as client:
        client.cookies.set(ADMIN_SESSION_COOKIE, create_admin_session_cookie())
        for route in routes:
            response = client.post(route, follow_redirects=False)
            assert response.status_code == 404
