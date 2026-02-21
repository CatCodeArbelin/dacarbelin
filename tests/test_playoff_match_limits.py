import unittest
from unittest.mock import AsyncMock

from app.models.tournament import PlayoffMatch, PlayoffParticipant, PlayoffStage
from app.services.tournament import apply_playoff_match_results


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class PlayoffMatchLimitsTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_stage_limit_blocks_fourth_game(self) -> None:
        ordered_user_ids = [1, 2, 3, 4, 5, 6, 7, 8]
        participants = [
            PlayoffParticipant(stage_id=1, user_id=user_id, seed=user_id, points=0, wins=0, top4_finishes=0, last_place=8)
            for user_id in ordered_user_ids
        ]

        for stage_key, stage_title in [
            ("stage_1_8", "Stage 1/8"),
            ("stage_1_4", "Stage 1/4"),
            ("stage_semifinal_groups", "Semifinal Groups"),
        ]:
            with self.subTest(stage_key=stage_key):
                stage = PlayoffStage(
                    id=1,
                    key=stage_key,
                    title=stage_title,
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

    async def test_final_stage_has_no_three_game_limit(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
