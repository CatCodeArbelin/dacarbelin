"""Проверяет ограничения по количеству матчей и переходам в плей-офф."""

import unittest
from unittest.mock import AsyncMock

from app.models.tournament import PlayoffMatch, PlayoffParticipant, PlayoffStage
from app.services.tournament import apply_playoff_match_results, playoff_sort_key


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

    async def test_stage_1_8_group_limit_blocks_fourth_game(self) -> None:
        """Проверяет негативный сценарий `test_stage_1_8_group_limit_blocks_fourth_game`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_playoff_match_limits.py -q` и `pytest tests/test_playoff_match_limits.py -k "test_stage_3_group_limit_blocks_fourth_game" -q`."""
        ordered_user_ids = [1, 2, 3, 4, 5, 6, 7, 8]
        participants = [
            PlayoffParticipant(stage_id=1, user_id=user_id, seed=user_id, points=0, wins=0, top4_finishes=0, last_place=8)
            for user_id in ordered_user_ids
        ]
        stage = PlayoffStage(
            id=1,
            key="stage_1_8",
            title="Stage 1/8",
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


    async def test_final_candidate_becomes_winner_only_after_next_top1(self) -> None:
        """Проверяет граничный сценарий `test_final_candidate_becomes_winner_only_after_next_top1`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_playoff_match_limits.py -q` и `pytest tests/test_playoff_match_limits.py -k "test_final_candidate_becomes_winner_only_after_next_top1" -q`."""
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

        for _ in range(3):
            await apply_playoff_match_results(db, stage_id=1, ordered_user_ids=ordered_user_ids, group_number=1)

        self.assertEqual(participants[0].points, 24)
        self.assertEqual(stage.final_candidate_user_id, 1)
        self.assertEqual(match.state, "in_progress")
        self.assertIsNone(match.winner_user_id)

        second_order = [2, 1, 3, 4, 5, 6, 7, 8]
        await apply_playoff_match_results(db, stage_id=1, ordered_user_ids=second_order, group_number=1)

        self.assertEqual(stage.final_candidate_user_id, 1)
        self.assertEqual(match.state, "in_progress")
        self.assertIsNone(match.winner_user_id)

        await apply_playoff_match_results(db, stage_id=1, ordered_user_ids=ordered_user_ids, group_number=1)

        self.assertEqual(match.state, "finished")
        self.assertEqual(match.winner_user_id, 1)

    def test_playoff_sort_key_prioritizes_points_for_remaining_places(self) -> None:
        """Проверяет `playoff_sort_key` для распределения мест по сумме очков."""
        p1 = PlayoffParticipant(stage_id=1, user_id=1, seed=1, points=16, wins=2, top4_finishes=2, last_place=2)
        p2 = PlayoffParticipant(stage_id=1, user_id=2, seed=2, points=18, wins=1, top4_finishes=1, last_place=8)
        p3 = PlayoffParticipant(stage_id=1, user_id=3, seed=3, points=16, wins=2, top4_finishes=2, last_place=1)

        ranked_ids = [p.user_id for p in sorted([p1, p2, p3], key=playoff_sort_key, reverse=True)]

        self.assertEqual(ranked_ids[0], 2)
        self.assertEqual(ranked_ids[1:], [3, 1])


if __name__ == "__main__":
    unittest.main()
