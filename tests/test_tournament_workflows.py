import unittest

from app.services.tournament import get_playoff_stage_blueprint, parse_manual_draw_user_ids


class TournamentWorkflowTests(unittest.TestCase):
    def test_parse_manual_draw_user_ids(self) -> None:
        self.assertEqual(parse_manual_draw_user_ids("1, 2,3"), [1, 2, 3])
        self.assertEqual(parse_manual_draw_user_ids(""), [])
        with self.assertRaises(ValueError):
            parse_manual_draw_user_ids("7,7")

    def test_playoff_stage_blueprint(self) -> None:
        stages_32 = get_playoff_stage_blueprint(32)
        self.assertEqual([stage[0] for stage in stages_32], [
            "playoff_1_16",
            "playoff_1_8",
            "playoff_1_4",
            "playoff_semifinal",
            "playoff_final",
        ])
        stages_8 = get_playoff_stage_blueprint(8)
        self.assertEqual([stage[0] for stage in stages_8], ["playoff_1_4", "playoff_semifinal", "playoff_final"])


if __name__ == "__main__":
    unittest.main()
