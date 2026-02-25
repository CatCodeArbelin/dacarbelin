"""Проверяет единый конфиг стадий турнира и его использование в view-логике."""

import unittest

from app.models.tournament import PlayoffMatch, PlayoffParticipant, PlayoffStage
from app.services.tournament_stage_config import (
    GROUP_STAGE_GAME_LIMIT,
    LIMITED_PLAYOFF_STAGE_KEYS,
    PROMOTE_TOP_N_BY_STAGE,
    get_game_limit,
    get_promote_top_n,
    is_limited_stage,
)
from app.services.tournament_view import build_playoff_standings


class TournamentStageConfigTests(unittest.TestCase):
    def test_stage_config_values_are_correct(self) -> None:
        self.assertEqual(GROUP_STAGE_GAME_LIMIT, 3)
        self.assertEqual(LIMITED_PLAYOFF_STAGE_KEYS, {"stage_2", "stage_1_8", "stage_1_4"})
        self.assertEqual(PROMOTE_TOP_N_BY_STAGE["stage_2"], 4)
        self.assertEqual(PROMOTE_TOP_N_BY_STAGE["stage_1_8"], 2)
        self.assertEqual(PROMOTE_TOP_N_BY_STAGE["stage_1_4"], 4)
        self.assertEqual(PROMOTE_TOP_N_BY_STAGE["stage_final"], 1)

    def test_stage_helpers_handle_required_stage_keys(self) -> None:
        self.assertTrue(is_limited_stage("stage_2"))
        self.assertTrue(is_limited_stage("stage_1_8"))
        self.assertTrue(is_limited_stage("stage_1_4"))
        self.assertFalse(is_limited_stage("stage_final"))

        self.assertEqual(get_game_limit("stage_2"), GROUP_STAGE_GAME_LIMIT)
        self.assertEqual(get_game_limit("stage_1_8"), GROUP_STAGE_GAME_LIMIT)
        self.assertEqual(get_game_limit("stage_1_4"), GROUP_STAGE_GAME_LIMIT)
        self.assertIsNone(get_game_limit("stage_final"))

        self.assertEqual(get_promote_top_n("stage_2"), 4)
        self.assertEqual(get_promote_top_n("stage_1_8"), 2)
        self.assertEqual(get_promote_top_n("stage_1_4"), 4)
        self.assertEqual(get_promote_top_n("stage_final"), 1)

    def test_build_playoff_standings_marks_status_by_configured_limits_and_promotion(self) -> None:
        stage = PlayoffStage(
            id=1,
            key="stage_1_8",
            title="Stage 1/8",
            stage_order=2,
            stage_size=8,
            scoring_mode="standard",
        )
        stage.matches = [
            PlayoffMatch(stage_id=1, match_number=1, group_number=1, game_number=GROUP_STAGE_GAME_LIMIT + 1, state="finished")
        ]
        stage.participants = [
            PlayoffParticipant(stage_id=1, user_id=1, seed=1, points=100, wins=3, top4_finishes=3, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=1, user_id=2, seed=2, points=90, wins=2, top4_finishes=3, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=1, user_id=3, seed=3, points=80, wins=1, top4_finishes=2, top8_finishes=3, last_place=8),
        ]

        standings = build_playoff_standings([stage], user_by_id={})
        statuses = [row["status"] for row in standings[0]["participants"]]

        self.assertEqual(statuses[:2], ["promoted", "promoted"])
        self.assertEqual(statuses[2], "eliminated")


if __name__ == "__main__":
    unittest.main()
