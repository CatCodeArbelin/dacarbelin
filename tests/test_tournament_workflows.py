import unittest

from app.services.tournament import (
    build_stage_2_player_ids,
    get_stage_group_number_by_seed,
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
        self.assertEqual(
            [stage[0] for stage in stages_32],
            [
                "stage_1_4",
                "stage_semifinal_groups",
                "stage_final",
            ],
        )
        self.assertEqual([stage[2] for stage in stages_32], [32, 16, 8])

    def test_stage_group_counts_for_new_playoff_flow(self) -> None:
        self.assertEqual(get_group_count_for_stage(56), 7)
        self.assertEqual(get_group_count_for_stage(32), 4)
        self.assertEqual(get_group_count_for_stage(16), 2)
        self.assertEqual(get_group_count_for_stage(8), 1)

    def test_stage_2_players_formed_as_21_plus_11(self) -> None:
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


    def test_stage_2_players_requires_exactly_21_promoted(self) -> None:
        with self.assertRaises(ValueError):
            build_stage_2_player_ids(list(range(1, 21)), list(range(101, 112)))

        with self.assertRaises(ValueError):
            build_stage_2_player_ids(list(range(1, 23)), list(range(101, 112)))

    def test_stage_2_players_validation_for_limit_and_duplicates(self) -> None:
        promoted = list(range(1, 22))

        with self.assertRaises(ValueError):
            build_stage_2_player_ids(promoted, list(range(101, 113)))

        with self.assertRaises(ValueError):
            build_stage_2_player_ids(promoted, [21, *range(101, 111)])


if __name__ == "__main__":
    unittest.main()
