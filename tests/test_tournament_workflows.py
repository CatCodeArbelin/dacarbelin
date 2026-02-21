import unittest

from app.services.tournament import (
    get_group_count_for_stage,
    get_playoff_stage_blueprint,
    parse_manual_draw_user_ids,
)


class TournamentWorkflowTests(unittest.TestCase):
    def test_parse_manual_draw_user_ids(self) -> None:
        self.assertEqual(parse_manual_draw_user_ids("1, 2,3"), [1, 2, 3])
        self.assertEqual(parse_manual_draw_user_ids(""), [])
        with self.assertRaises(ValueError):
            parse_manual_draw_user_ids("7,7")

    def test_playoff_stage_blueprint(self) -> None:
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
        self.assertEqual(stages_32, [])

    def test_stage_group_counts_for_new_playoff_flow(self) -> None:
        self.assertEqual(get_group_count_for_stage(56), 7)
        self.assertEqual(get_group_count_for_stage(32), 4)
        self.assertEqual(get_group_count_for_stage(16), 2)
        self.assertEqual(get_group_count_for_stage(8), 1)


if __name__ == "__main__":
    unittest.main()
