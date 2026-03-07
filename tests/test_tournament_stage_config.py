"""Проверяет единый конфиг стадий турнира и его использование в view-логике."""

import unittest

from app.routers import web
from app.models.tournament import PlayoffMatch, PlayoffParticipant, PlayoffStage
from app.services.tournament_stage_config import (
    ADMIN_PLAYOFF_STAGE_CONFIGS,
    GROUP_STAGE_GAME_LIMIT,
    LEGACY_STAGE_KEY_ALIASES,
    TOURNAMENT_FLOW_SPEC,
    TOURNAMENT_PROFILE_SPECS,
    get_tournament_profile_spec,
    LIMITED_PLAYOFF_STAGE_KEYS,
    PROMOTE_TOP_N_BY_STAGE,
    get_admin_playoff_stage_config,
    get_game_limit,
    get_promote_top_n,
    is_final_stage,
    is_final_stage_key,
    is_limited_stage,
    normalize_stage_key,
)
from app.services.tournament import get_playoff_stage_columns, get_playoff_stage_sequence_keys, get_public_stage_display_sequence
from app.services.tournament_view import build_playoff_standings, resolve_current_stage_label


class TournamentStageConfigTests(unittest.TestCase):
    def test_stage_config_values_are_correct(self) -> None:
        self.assertEqual(GROUP_STAGE_GAME_LIMIT, 3)
        self.assertEqual(TOURNAMENT_FLOW_SPEC["group_stage"]["participants"], 56)
        self.assertEqual(TOURNAMENT_FLOW_SPEC["group_stage"]["groups_count"], 7)
        self.assertEqual(LIMITED_PLAYOFF_STAGE_KEYS, {"stage_2", "stage_1_4"})
        self.assertEqual(set(TOURNAMENT_PROFILE_SPECS.keys()), {"56", "48"})
        self.assertEqual(get_tournament_profile_spec("48")["stage_1_groups_count"], 6)
        self.assertEqual(PROMOTE_TOP_N_BY_STAGE["stage_2"], 4)
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
            for stage_key in ["stage_2", "stage_1_4"]
        ]
        self.assertTrue(all(not config.is_final for config in non_final_configs))
        self.assertTrue(all(config.game_limit == GROUP_STAGE_GAME_LIMIT for config in non_final_configs))
        self.assertTrue(all(config.can_debug_simulate for config in non_final_configs))

    def test_stage_helpers_handle_required_stage_keys(self) -> None:
        self.assertTrue(is_limited_stage("stage_2"))
        self.assertTrue(is_limited_stage("stage_1_4"))
        self.assertFalse(is_limited_stage("stage_final"))

        self.assertEqual(get_game_limit("stage_2"), GROUP_STAGE_GAME_LIMIT)
        self.assertEqual(get_game_limit("stage_1_4"), GROUP_STAGE_GAME_LIMIT)
        self.assertIsNone(get_game_limit("stage_final"))

        self.assertEqual(get_promote_top_n("stage_2"), 4)
        self.assertEqual(get_promote_top_n("stage_1_4"), 4)
        self.assertEqual(get_promote_top_n("stage_final"), 1)

    def test_stage_sequence_is_shared_across_service_and_view_layers(self) -> None:
        self.assertEqual(get_playoff_stage_sequence_keys(), ["stage_2", "stage_1_4", "stage_final"])
        self.assertEqual(
            [stage_key for stage_key, _ in get_playoff_stage_columns()],
            get_playoff_stage_sequence_keys(),
        )
        self.assertEqual(get_public_stage_display_sequence(), ["group_stage", *get_playoff_stage_sequence_keys()])

    def test_legacy_stage_key_aliases_map_to_current_final_stage(self) -> None:
        self.assertEqual(LEGACY_STAGE_KEY_ALIASES["final"], "stage_final")
        self.assertEqual(LEGACY_STAGE_KEY_ALIASES["stage_4"], "stage_final")
        self.assertEqual(normalize_stage_key("final"), "stage_final")
        self.assertEqual(normalize_stage_key("stage_4"), "stage_final")
        self.assertEqual(normalize_stage_key("stage4"), "stage_final")
        self.assertEqual(normalize_stage_key("stage_4_final"), "stage_final")
        self.assertEqual(normalize_stage_key("stage_1_8"), "stage_2")
        self.assertEqual(normalize_stage_key("stage_3"), "stage_1_4")

        legacy_final_config = get_admin_playoff_stage_config("final")
        legacy_stage_4_config = get_admin_playoff_stage_config("stage_4")
        canonical_final_config = get_admin_playoff_stage_config("stage_final")

        self.assertEqual(legacy_final_config, canonical_final_config)
        self.assertEqual(legacy_stage_4_config, canonical_final_config)
        self.assertTrue(legacy_final_config.is_final)
        self.assertIsNone(get_game_limit("final"))
        self.assertIsNone(get_game_limit("stage_4"))
        self.assertEqual(get_promote_top_n("final"), 1)
        self.assertEqual(get_promote_top_n("stage_4"), 1)
        self.assertFalse(is_limited_stage("final"))
        self.assertFalse(is_limited_stage("stage_4"))



    def test_stage_submit_contracts_for_all_tournament_stages(self) -> None:
        stages = [
            ("stage_2", 32, "standard", True),
            ("stage_1_4", 16, "standard", True),
            ("stage_final", 8, "final_22_top1", True),
            ("group_stage", 56, "standard", False),
        ]

        for key, stage_size, scoring_mode, expected in stages:
            stage = PlayoffStage(
                id=1,
                key=key,
                title=key,
                stage_order=1,
                stage_size=stage_size,
                scoring_mode=scoring_mode,
            )
            status = web.get_playoff_stage_submit_status(stage)
            self.assertEqual(status["can_submit"], expected, key)

    def test_stage_submit_contract_rejects_unknown_non_final_stage(self) -> None:
        stage = PlayoffStage(
            id=10,
            key="mystery_stage",
            title="Mystery",
            stage_order=1,
            stage_size=16,
            scoring_mode="standard",
        )
        status = web.get_playoff_stage_submit_status(stage)
        self.assertFalse(status["can_submit"])
        self.assertEqual(status["reason"], "stage_key_unrecognized")

    def test_final_stage_detection_supports_legacy_and_scoring_mode(self) -> None:
        self.assertTrue(is_final_stage_key("stage_final"))
        self.assertTrue(is_final_stage_key("final"))
        self.assertTrue(is_final_stage_key(" STAGE_4 "))

        self.assertTrue(is_final_stage("custom_final", scoring_mode="final_22_top1"))
        self.assertTrue(is_final_stage("unknown", stage_size=8))
        self.assertTrue(is_final_stage("unknown", stage_size="8"))
        self.assertTrue(is_final_stage("stage_4_final", stage_size=16, scoring_mode="standard"))
        self.assertFalse(is_final_stage("stage_1_4", stage_size=16, scoring_mode="standard"))

    def test_playoff_stage_integrity_alert_detects_invalid_final_stage(self) -> None:
        stages = [
            PlayoffStage(id=1, key="stage_2", title="Stage 2", stage_order=0, stage_size=32, scoring_mode="standard"),
            PlayoffStage(id=2, key="stage_1_4", title="Stage 3", stage_order=1, stage_size=16, scoring_mode="standard"),
            PlayoffStage(id=3, key="invalid_final", title="Final", stage_order=2, stage_size=16, scoring_mode="standard"),
        ]

        alert = web.get_playoff_stage_integrity_alert(stages)

        self.assertIsNotNone(alert)
        assert alert is not None
        self.assertIn("неизвестный key='invalid_final'", alert)
        self.assertIn("нарушены пары (stage_order, key)", alert)
        self.assertIn("должна иметь stage_size=8", alert)
        self.assertIn("scoring_mode='final_22_top1'", alert)

    def test_playoff_integrity_treats_legacy_keys_as_known_not_unknown(self) -> None:
        stages = [
            PlayoffStage(id=1, key="stage_2", title="Stage 2", stage_order=0, stage_size=32, scoring_mode="standard"),
            PlayoffStage(id=2, key="stage_1_4", title="Stage 3", stage_order=1, stage_size=16, scoring_mode="standard"),
            PlayoffStage(id=3, key="final", title="Final", stage_order=2, stage_size=8, scoring_mode="final_22_top1"),
        ]

        alert = web.get_playoff_stage_integrity_alert(stages)

        self.assertIsNotNone(alert)
        assert alert is not None
        self.assertNotIn("неизвестный key='final'", alert)
        self.assertIn("legacy alias key='final'", alert)

    def test_playoff_integrity_reports_extra_stage_without_masking_missing_required_pair(self) -> None:
        stages = [
            PlayoffStage(id=1, key="stage_2", title="Stage 2", stage_order=0, stage_size=32, scoring_mode="standard"),
            PlayoffStage(id=2, key="stage_1_4", title="Stage 3", stage_order=1, stage_size=16, scoring_mode="standard"),
            PlayoffStage(id=3, key="stage_final", title="Final", stage_order=5, stage_size=8, scoring_mode="final_22_top1"),
            PlayoffStage(id=4, key="stage_2", title="Unexpected Stage", stage_order=3, stage_size=8, scoring_mode="standard"),
        ]

        alert = web.get_playoff_stage_integrity_alert(stages)

        self.assertIsNotNone(alert)
        assert alert is not None
        self.assertIn("отсутствуют обязательные пары", alert)
        self.assertIn("лишние playoff-стадии", alert)
        self.assertIn("(5, stage_final)", alert)

    def test_playoff_integrity_reports_unknown_key_explicitly(self) -> None:
        stages = [
            PlayoffStage(id=1, key="stage_2", title="Stage 2", stage_order=0, stage_size=32, scoring_mode="standard"),
            PlayoffStage(id=2, key="mystery_stage", title="Mystery", stage_order=1, stage_size=16, scoring_mode="standard"),
            PlayoffStage(id=3, key="stage_final", title="Final", stage_order=2, stage_size=8, scoring_mode="final_22_top1"),
        ]

        alert = web.get_playoff_stage_integrity_alert(stages)

        self.assertIsNotNone(alert)
        assert alert is not None
        self.assertIn("неизвестный key='mystery_stage'", alert)

    def test_build_playoff_standings_marks_status_by_configured_limits_and_promotion(self) -> None:
        stage = PlayoffStage(
            id=1,
            key="stage_1_4",
            title="Stage 3",
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
            PlayoffParticipant(stage_id=1, user_id=4, seed=4, points=70, wins=1, top4_finishes=2, top8_finishes=3, last_place=8),
        ]

        standings = build_playoff_standings([stage], user_by_id={})
        statuses = [row["status"] for row in standings[0]["participants"]]

        self.assertEqual(statuses, ["promoted", "promoted", "promoted", "promoted"])

    def test_resolve_current_stage_label_returns_group_stage_when_playoff_hidden(self) -> None:
        stages = [
            PlayoffStage(id=1, key="stage_2", title="Stage 2", stage_order=1, stage_size=32, is_started=False),
            PlayoffStage(id=2, key="stage_1_4", title="Stage 3", stage_order=2, stage_size=16, is_started=False),
        ]

        self.assertEqual(resolve_current_stage_label("ru", stages, show_playoff=False), web.t("ru", "tournament_stage_group_stage_label"))

    def test_resolve_current_stage_label_supports_existing_stage_keys(self) -> None:
        stages = [
            PlayoffStage(id=1, key="stage_2", title="Stage 2", stage_order=1, stage_size=32, is_started=False),
            PlayoffStage(id=2, key="stage_1_4", title="Stage 3", stage_order=2, stage_size=16, is_started=False),
            PlayoffStage(id=3, key="stage_final", title="Final", stage_order=3, stage_size=8, is_started=False),
        ]

        self.assertEqual(resolve_current_stage_label("ru", stages, show_playoff=True), "II этап 1/4 (32, 4x8, top-4)")

        stages[1].is_started = True
        self.assertEqual(resolve_current_stage_label("ru", stages, show_playoff=True), "III этап полуфинальные группы (16, 2x8, top-4)")

        stages[1].is_started = False
        stages[2].is_started = True
        self.assertEqual(resolve_current_stage_label("ru", stages, show_playoff=True), "Финал (8, правило 22+победа)")


if __name__ == "__main__":
    unittest.main()
