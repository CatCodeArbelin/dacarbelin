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


def test_stage_3_highlights_top_4() -> None:
    rows = _apply_stage_highlight_rules("stage_1_4", _participants([24, 18, 15, 12, 9, 6, 3, 0]))
    highlighted = [row.get("is_promoted_highlight", False) for row in rows]
    assert highlighted == [True, True, True, True, False, False, False, False]


def test_final_legacy_key_highlights_players_with_22_plus() -> None:
    rows = _apply_stage_highlight_rules("stage_4", _participants([30, 24, 22, 21, 18, 12, 6, 0]))
    highlighted = [row.get("is_promoted_highlight", False) for row in rows]
    assert highlighted == [True, True, True, False, False, False, False, False]
