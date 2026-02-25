"""Проверяет единый конфиг стадий турнира и его использование в view-логике."""

import unittest

from app.models.tournament import PlayoffMatch, PlayoffParticipant, PlayoffStage
from app.services.tournament_stage_config import (
    ADMIN_PLAYOFF_STAGE_CONFIGS,
    GROUP_STAGE_GAME_LIMIT,
    LIMITED_PLAYOFF_STAGE_KEYS,
    PROMOTE_TOP_N_BY_STAGE,
    get_admin_playoff_stage_config,
    get_game_limit,
    get_promote_top_n,
    is_limited_stage,
)
from app.services.tournament import get_playoff_stage_columns, get_playoff_stage_sequence_keys, get_public_stage_display_sequence
from app.services.tournament_view import build_playoff_standings


class TournamentStageConfigTests(unittest.TestCase):
    def test_stage_config_values_are_correct(self) -> None:
        self.assertEqual(GROUP_STAGE_GAME_LIMIT, 3)
        self.assertEqual(LIMITED_PLAYOFF_STAGE_KEYS, {"stage_2", "stage_1_8", "stage_1_4"})
        self.assertEqual(PROMOTE_TOP_N_BY_STAGE["stage_2"], 4)
        self.assertEqual(PROMOTE_TOP_N_BY_STAGE["stage_1_8"], 2)
        self.assertEqual(PROMOTE_TOP_N_BY_STAGE["stage_1_4"], 4)
        self.assertEqual(PROMOTE_TOP_N_BY_STAGE["stage_final"], 1)

    def test_admin_stage_config_is_predictable_for_every_known_stage(self) -> None:
        expected = {
            "stage_2": {
                "can_shuffle": True,
                "can_debug_simulate": True,
                "game_limit": GROUP_STAGE_GAME_LIMIT,
                "promote_top_n": 4,
                "is_final": False,
            },
            "stage_1_8": {
                "can_shuffle": False,
                "can_debug_simulate": True,
                "game_limit": GROUP_STAGE_GAME_LIMIT,
                "promote_top_n": 2,
                "is_final": False,
            },
            "stage_1_4": {
                "can_shuffle": False,
                "can_debug_simulate": True,
                "game_limit": GROUP_STAGE_GAME_LIMIT,
                "promote_top_n": 4,
                "is_final": False,
            },
            "stage_final": {
                "can_shuffle": False,
                "can_debug_simulate": False,
                "game_limit": None,
                "promote_top_n": 1,
                "is_final": True,
            },
        }

        self.assertEqual(set(ADMIN_PLAYOFF_STAGE_CONFIGS), set(expected))

        for stage_key, values in expected.items():
            config = get_admin_playoff_stage_config(stage_key)
            self.assertEqual(config.can_shuffle, values["can_shuffle"], stage_key)
            self.assertEqual(config.can_debug_simulate, values["can_debug_simulate"], stage_key)
            self.assertEqual(config.game_limit, values["game_limit"], stage_key)
            self.assertEqual(config.promote_top_n, values["promote_top_n"], stage_key)
            self.assertEqual(config.is_final, values["is_final"], stage_key)

        non_final_configs = [
            get_admin_playoff_stage_config(stage_key)
            for stage_key in ["stage_2", "stage_1_8", "stage_1_4"]
        ]
        self.assertTrue(all(not config.is_final for config in non_final_configs))
        self.assertTrue(all(config.game_limit == GROUP_STAGE_GAME_LIMIT for config in non_final_configs))
        self.assertTrue(all(config.can_debug_simulate for config in non_final_configs))

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

    def test_stage_sequence_is_shared_across_service_and_view_layers(self) -> None:
        self.assertEqual(get_playoff_stage_sequence_keys(), ["stage_2", "stage_1_4", "stage_final"])
        self.assertEqual(
            [stage_key for stage_key, _ in get_playoff_stage_columns()],
            get_playoff_stage_sequence_keys(),
        )
        self.assertEqual(get_public_stage_display_sequence(), ["group_stage", *get_playoff_stage_sequence_keys()])

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
