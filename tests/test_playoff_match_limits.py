"""Проверяет ограничения по количеству матчей и переходам в плей-офф."""

import unittest
from unittest.mock import AsyncMock

from app.models.tournament import PlayoffMatch, PlayoffParticipant, PlayoffStage
from app.services.tournament import (
    apply_playoff_match_results,
    playoff_sort_key,
    simulate_three_random_games_for_stage,
)


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class PlayoffMatchLimitsTests(unittest.IsolatedAsyncioTestCase):
    async def test_stage_2_group_limit_blocks_fourth_game(self) -> None:
        """Проверяет негативный сценарий `test_stage_2_group_limit_blocks_fourth_game`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_playoff_match_limits.py -q` и `pytest tests/test_playoff_match_limits.py -k "test_stage_2_group_limit_blocks_fourth_game" -q`."""
        ordered_user_ids = [1, 2, 3, 4, 5, 6, 7, 8]
        participants = [
            PlayoffParticipant(stage_id=1, user_id=user_id, seed=user_id, points=0, wins=0, top4_finishes=0, last_place=8)
            for user_id in ordered_user_ids
        ]
        stage = PlayoffStage(
            id=1,
            key="stage_2",
            title="Stage 2",
            stage_size=8,
            stage_order=1,
            scoring_mode="standard",
        )
        match = PlayoffMatch(stage_id=1, match_number=1, group_number=1, game_number=4)

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage, match])
        db.scalars = AsyncMock(return_value=_ScalarResult(participants))

        with self.assertRaisesRegex(ValueError, "достигнут лимит"):
            await apply_playoff_match_results(db, stage_id=1, ordered_user_ids=ordered_user_ids, group_number=1)

        db.commit.assert_not_called()


    async def test_limited_stage_moves_to_finished_after_third_game(self) -> None:
        """Проверяет завершение группы после третьей сыгранной игры на лимитируемых стадиях."""
        ordered_user_ids = [1, 2, 3, 4, 5, 6, 7, 8]
        participants = [
            PlayoffParticipant(stage_id=1, user_id=user_id, seed=user_id, points=0, wins=0, top4_finishes=0, last_place=8)
            for user_id in ordered_user_ids
        ]
        stage = PlayoffStage(
            id=1,
            key="stage_2",
            title="Stage 2",
            stage_size=8,
            stage_order=1,
            scoring_mode="standard",
        )
        match = PlayoffMatch(stage_id=1, match_number=1, group_number=1, game_number=3, state="in_progress")

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage, match])
        db.scalars = AsyncMock(return_value=_ScalarResult(participants))

        await apply_playoff_match_results(db, stage_id=1, ordered_user_ids=ordered_user_ids, group_number=1)

        self.assertEqual(match.game_number, 4)
        self.assertEqual(match.state, "finished")
        db.commit.assert_called_once()

    async def test_stage_1_4_group_limit_blocks_fourth_game(self) -> None:
        """Проверяет негативный сценарий `test_stage_1_4_group_limit_blocks_fourth_game`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_playoff_match_limits.py -q` и `pytest tests/test_playoff_match_limits.py -k "test_stage_3_group_limit_blocks_fourth_game" -q`."""
        ordered_user_ids = [1, 2, 3, 4, 5, 6, 7, 8]
        participants = [
            PlayoffParticipant(stage_id=1, user_id=user_id, seed=user_id, points=0, wins=0, top4_finishes=0, last_place=8)
            for user_id in ordered_user_ids
        ]
        stage = PlayoffStage(
            id=1,
            key="stage_1_4",
            title="Stage 1/4",
            stage_size=8,
            stage_order=2,
            scoring_mode="standard",
        )
        match = PlayoffMatch(stage_id=1, match_number=1, group_number=1, game_number=4)

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage, match])
        db.scalars = AsyncMock(return_value=_ScalarResult(participants))

        with self.assertRaisesRegex(ValueError, "достигнут лимит"):
            await apply_playoff_match_results(db, stage_id=1, ordered_user_ids=ordered_user_ids, group_number=1)

        db.commit.assert_not_called()

    async def test_final_stage_has_no_three_game_limit(self) -> None:
        """Проверяет граничный сценарий `test_final_stage_has_no_three_game_limit`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_playoff_match_limits.py -q` и `pytest tests/test_playoff_match_limits.py -k "test_final_stage_has_no_three_game_limit" -q`."""
        ordered_user_ids = [1, 2, 3, 4, 5, 6, 7, 8]
        participants = [
            PlayoffParticipant(stage_id=1, user_id=user_id, seed=user_id, points=0, wins=0, top4_finishes=0, last_place=8)
            for user_id in ordered_user_ids
        ]
        stage = PlayoffStage(
            id=1,
            key="stage_final",
            title="Final",
            stage_size=8,
            stage_order=4,
            scoring_mode="final_22_top1",
        )
        match = PlayoffMatch(stage_id=1, match_number=1, group_number=1, game_number=4)

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage, match])
        db.scalars = AsyncMock(return_value=_ScalarResult(participants))

        await apply_playoff_match_results(db, stage_id=1, ordered_user_ids=ordered_user_ids, group_number=1)

        self.assertEqual(match.game_number, 5)
        self.assertEqual(match.state, "in_progress")
        db.commit.assert_called_once()


    async def test_final_stage_does_not_auto_finish_after_threshold_or_extra_games(self) -> None:
        """Проверяет, что финал не закрывается автоматически по порогу очков."""
        ordered_user_ids = [1, 2, 3, 4, 5, 6, 7, 8]
        participants = [
            PlayoffParticipant(stage_id=1, user_id=user_id, seed=user_id, points=0, wins=0, top4_finishes=0, last_place=8)
            for user_id in ordered_user_ids
        ]
        stage = PlayoffStage(
            id=1,
            key="stage_final",
            title="Final",
            stage_size=8,
            stage_order=4,
            scoring_mode="final_22_top1",
            final_candidate_user_id=None,
        )
        match = PlayoffMatch(stage_id=1, match_number=1, group_number=1, game_number=1, state="in_progress")

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage, match, stage, match, stage, match, stage, match, stage, match])
        db.scalars = AsyncMock(return_value=_ScalarResult(participants))

        for _ in range(5):
            await apply_playoff_match_results(db, stage_id=1, ordered_user_ids=ordered_user_ids, group_number=1)

        self.assertEqual(participants[0].points, 40)
        self.assertEqual(stage.final_candidate_user_id, None)
        self.assertEqual(match.state, "in_progress")
        self.assertIsNone(match.winner_user_id)


    async def test_final_stage_does_not_set_candidate_at_22_points_threshold(self) -> None:
        ordered_user_ids = [1, 2, 3, 4, 5, 6, 7, 8]
        participants = [
            PlayoffParticipant(stage_id=1, user_id=user_id, seed=user_id, points=0, wins=0, top4_finishes=0, last_place=8)
            for user_id in ordered_user_ids
        ]
        participants[0].points = 21

        stage = PlayoffStage(
            id=1,
            key="stage_final",
            title="Final",
            stage_size=8,
            stage_order=4,
            scoring_mode="final_22_top1",
            final_candidate_user_id=None,
        )
        match = PlayoffMatch(stage_id=1, match_number=1, group_number=1, game_number=1, state="in_progress")

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage, match])
        db.scalars = AsyncMock(return_value=_ScalarResult(participants))

        await apply_playoff_match_results(db, stage_id=1, ordered_user_ids=[2, 3, 4, 5, 6, 7, 1, 8], group_number=1)

        self.assertEqual(participants[0].points, 22)
        self.assertIsNone(stage.final_candidate_user_id)
        self.assertEqual(match.state, "in_progress")

    async def test_apply_playoff_match_results_increments_eighth_places_for_each_stage(self) -> None:
        """Проверяет инкремент 8-х мест во всех стадиях плей-офф."""
        ordered_user_ids = [1, 2, 3, 4, 5, 6, 7, 8]

        for stage_key, scoring_mode in (("stage_2", "standard"), ("stage_1_4", "standard"), ("stage_final", "final_22_top1")):
            with self.subTest(stage_key=stage_key):
                participants = [
                    PlayoffParticipant(
                        stage_id=1,
                        user_id=user_id,
                        seed=user_id,
                        points=0,
                        wins=0,
                        top4_finishes=0,
                        top8_finishes=0,
                        eighth_places=0,
                        last_place=8,
                    )
                    for user_id in ordered_user_ids
                ]
                stage = PlayoffStage(
                    id=1,
                    key=stage_key,
                    title=stage_key,
                    stage_size=8,
                    stage_order=1,
                    scoring_mode=scoring_mode,
                )
                match = PlayoffMatch(stage_id=1, match_number=1, group_number=1, game_number=1, state="pending")

                db = AsyncMock()
                db.scalar = AsyncMock(side_effect=[stage, match])
                db.scalars = AsyncMock(return_value=_ScalarResult(participants))

                await apply_playoff_match_results(db, stage_id=1, ordered_user_ids=ordered_user_ids, group_number=1)

                eighth_place_participant = next(item for item in participants if item.user_id == 8)
                self.assertEqual(eighth_place_participant.eighth_places, 1)

                non_eighth_place_participants = [item for item in participants if item.user_id != 8]
                self.assertTrue(all(item.eighth_places == 0 for item in non_eighth_place_participants))

    def test_playoff_sort_key_prioritizes_points_for_remaining_places(self) -> None:
        """Проверяет `playoff_sort_key` для распределения мест по сумме очков."""
        p1 = PlayoffParticipant(stage_id=1, user_id=1, seed=1, points=16, wins=2, top4_finishes=2, last_place=2)
        p2 = PlayoffParticipant(stage_id=1, user_id=2, seed=2, points=18, wins=1, top4_finishes=1, last_place=8)
        p3 = PlayoffParticipant(stage_id=1, user_id=3, seed=3, points=16, wins=2, top4_finishes=2, last_place=1)

        ranked_ids = [p.user_id for p in sorted([p1, p2, p3], key=playoff_sort_key, reverse=True)]

        self.assertEqual(ranked_ids[0], 2)
        self.assertEqual(ranked_ids[1:], [3, 1])


    async def test_debug_simulation_plays_three_games_for_full_group_in_each_limited_stage(self) -> None:
        for stage_id, stage_key, stage_title in (
            (11, "stage_2", "Stage 2"),
            (12, "stage_1_4", "Stage 1/4"),
        ):
            stage = PlayoffStage(
                id=stage_id,
                key=stage_key,
                title=stage_title,
                stage_size=8,
                stage_order=1,
                scoring_mode="standard",
            )
            match = PlayoffMatch(stage_id=stage_id, match_number=1, group_number=1, game_number=1, state="pending")
            participants = [
                PlayoffParticipant(stage_id=stage_id, user_id=user_id, seed=user_id, points=0, wins=0, top4_finishes=0, last_place=8)
                for user_id in range(1, 9)
            ]

            db = AsyncMock()
            db.scalars = AsyncMock(return_value=_ScalarResult(participants))
            db.scalar = AsyncMock(side_effect=[stage, stage, match, stage, match, stage, match])

            await simulate_three_random_games_for_stage(db, stage_id)

            self.assertEqual(match.game_number, 4)
            self.assertEqual(match.state, "finished")
            self.assertEqual(db.commit.await_count, 3)

    async def test_debug_simulation_affects_only_requested_stage(self) -> None:
        selected_stage = PlayoffStage(
            id=21,
            key="stage_1_4",
            title="Stage 1/4",
            stage_size=8,
            stage_order=2,
            scoring_mode="standard",
        )
        selected_match = PlayoffMatch(stage_id=21, match_number=1, group_number=1, game_number=1, state="pending")
        selected_participants = [
            PlayoffParticipant(stage_id=21, user_id=user_id, seed=user_id, points=0, wins=0, top4_finishes=0, last_place=8)
            for user_id in range(1, 9)
        ]
        other_match = PlayoffMatch(stage_id=22, match_number=1, group_number=1, game_number=1, state="pending")

        db = AsyncMock()
        db.scalars = AsyncMock(return_value=_ScalarResult(selected_participants))
        db.scalar = AsyncMock(side_effect=[selected_stage, selected_stage, selected_match, selected_stage, selected_match, selected_stage, selected_match])

        await simulate_three_random_games_for_stage(db, selected_stage.id)

        self.assertEqual(selected_match.game_number, 4)
        self.assertEqual(selected_match.state, "finished")
        self.assertEqual(other_match.game_number, 1)

    async def test_debug_simulation_skips_non_limited_stage(self) -> None:
        stage = PlayoffStage(
            id=31,
            key="stage_final",
            title="Final",
            stage_size=8,
            stage_order=4,
            scoring_mode="final_22_top1",
        )

        db = AsyncMock()
        db.scalar = AsyncMock(return_value=stage)

        await simulate_three_random_games_for_stage(db, stage.id)

        db.scalars.assert_not_called()
        db.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
