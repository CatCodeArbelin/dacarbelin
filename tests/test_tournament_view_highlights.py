"""Проверяет подсветку проходящих участников на турнирной странице."""

from app.services.tournament_view import _apply_stage_highlight_rules


def _participants(points: list[int]) -> list[dict]:
    return [
        {"user_id": idx + 1, "nickname": f"P{idx+1}", "points": pts, "is_direct_invite_preview": False}
        for idx, pts in enumerate(points)
    ]


def test_stage_2_highlights_top_4() -> None:
    rows = _apply_stage_highlight_rules("stage_2", _participants([24, 18, 15, 12, 9, 6, 3, 0]))
    highlighted = [row.get("is_promoted_highlight", False) for row in rows]
    assert highlighted == [True, True, True, True, False, False, False, False]


def test_stage_1_highlights_top_3() -> None:
    rows = _apply_stage_highlight_rules("group_stage", _participants([24, 18, 15, 12, 9, 6, 3, 0]))
    highlighted = [row.get("is_promoted_highlight", False) for row in rows]
    assert highlighted == [True, True, True, False, False, False, False, False]


def test_stage_3_highlights_top_4() -> None:
    rows = _apply_stage_highlight_rules("stage_1_4", _participants([24, 18, 15, 12, 9, 6, 3, 0]))
    highlighted = [row.get("is_promoted_highlight", False) for row in rows]
    assert highlighted == [True, True, True, True, False, False, False, False]


def test_final_legacy_key_uses_podium_colors() -> None:
    rows = _apply_stage_highlight_rules("stage_4", _participants([30, 24, 22, 21, 18, 12, 6, 0]))
    colors = [row.get("highlight_color") for row in rows]
    assert colors == ["gold", "silver", "bronze", "eliminated", "eliminated", "eliminated", "eliminated", "eliminated"]


def test_stage_2_sets_highlight_colors() -> None:
    rows = _apply_stage_highlight_rules("stage_2", _participants([24, 18, 15, 12, 9, 6, 3, 0]))
    colors = [row.get("highlight_color") for row in rows]
    assert colors == ["promoted", "promoted", "promoted", "promoted", "eliminated", "eliminated", "eliminated", "eliminated"]


def test_final_sets_podium_highlight_colors_without_winner() -> None:
    rows = _apply_stage_highlight_rules("stage_final", _participants([30, 24, 22, 21, 18, 12, 6, 0]))
    colors = [row.get("highlight_color") for row in rows]
    assert colors == ["gold", "silver", "bronze", "eliminated", "eliminated", "eliminated", "eliminated", "eliminated"]


def test_final_winner_gets_gold_before_points_ranking() -> None:
    rows = _participants([30, 24, 22, 21])
    rows[2]["is_tournament_winner"] = True
    rows = _apply_stage_highlight_rules("stage_final", rows)
    colors = [row.get("highlight_color") for row in rows]
    assert colors == ["silver", "bronze", "gold", "eliminated"]


def test_stage_highlights_disabled_until_first_game_played() -> None:
    rows = _apply_stage_highlight_rules("group_stage", _participants([0, 0, 0, 0]))
    highlighted = [row.get("is_promoted_highlight", False) for row in rows]
    colors = [row.get("highlight_color") for row in rows]
    assert highlighted == [False, False, False, False]
    assert colors == [None, None, None, None]


def test_stage_2_highlights_disabled_until_first_game_played() -> None:
    rows = _apply_stage_highlight_rules("stage_2", _participants([0, 0, 0, 0]))
    highlighted = [row.get("is_promoted_highlight", False) for row in rows]
    colors = [row.get("highlight_color") for row in rows]
    assert highlighted == [False, False, False, False]
    assert colors == [None, None, None, None]
