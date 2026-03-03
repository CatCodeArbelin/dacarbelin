"""Проверяет автопереход стадии после завершения активных групп."""

import unittest
from unittest.mock import AsyncMock, patch

from app.models.tournament import PlayoffMatch, PlayoffParticipant, PlayoffStage
from app.routers import web
from app.services import tournament


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class PlayoffGroupFinishFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_stage_is_finished_by_active_groups_only(self) -> None:
        stage = PlayoffStage(id=10, key="stage_2", title="Stage 2", stage_order=0)
        participants = [
            PlayoffParticipant(stage_id=10, user_id=user_id, seed=seed, points=0, wins=0, top4_finishes=0, top8_finishes=0, last_place=8)
            for seed, user_id in enumerate(range(100, 116), start=1)
        ]
        # Активны только группы 1-2 (16 участников), группы 3-4 пустые.
        group_2_match = PlayoffMatch(stage_id=10, group_number=2, game_number=4, state="in_progress")
        group_1_match = PlayoffMatch(stage_id=10, group_number=1, game_number=4, state="finished")
        group_2_finished = PlayoffMatch(stage_id=10, group_number=2, game_number=4, state="finished")

        db = AsyncMock()
        db.scalars = AsyncMock(return_value=_ScalarResult(participants))
        db.scalar = AsyncMock(side_effect=[stage, group_2_match, group_1_match, group_2_finished, None])

        with (
            patch.object(web, "promote_top_between_stages", new=AsyncMock()) as promote_mock,
            patch.object(web, "start_playoff_stage", new=AsyncMock()) as start_mock,
        ):
            response = await web.admin_finish_playoff_group(stage_id=10, group_number=2, db=db)

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=msg_status_ok", response.headers["location"])
        self.assertIn("details=use_stage_finish", response.headers["location"])
        promote_mock.assert_not_awaited()
        start_mock.assert_not_awaited()

    async def test_finish_active_playoff_stage_promotes_and_starts_next(self) -> None:
        stage = PlayoffStage(id=20, key="stage_2", title="Stage 2", stage_order=1, is_started=True)
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage])

        with patch.object(web, "finalize_limited_playoff_stage_if_ready", new=AsyncMock(return_value=True)) as finalize_mock:
            response = await web.admin_finish_playoff_stage(stage_id=20, db=db)

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=msg_status_ok", response.headers["location"])
        finalize_mock.assert_awaited_once_with(db, 20)

    async def test_finish_stage_requires_expected_group_coverage(self) -> None:
        stage = PlayoffStage(id=30, key="stage_2", title="Stage 2", stage_order=1, is_started=True, stage_size=32)
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage])

        with patch.object(
            web,
            "finalize_limited_playoff_stage_if_ready",
            new=AsyncMock(side_effect=ValueError("stage_groups_missing")),
        ):
            response = await web.admin_finish_playoff_stage(stage_id=30, db=db)

        self.assertEqual(response.status_code, 303)
        self.assertIn("details=stage_groups_missing", response.headers["location"])

    async def test_finish_stage_blocks_promote_size_mismatch(self) -> None:
        stage = PlayoffStage(id=40, key="stage_2", title="Stage 2", stage_order=1, is_started=True, stage_size=32)
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage])

        with patch.object(
            web,
            "finalize_limited_playoff_stage_if_ready",
            new=AsyncMock(side_effect=ValueError("promoted_size_mismatch")),
        ):
            response = await web.admin_finish_playoff_stage(stage_id=40, db=db)

        self.assertEqual(response.status_code, 303)
        self.assertIn("details=promoted_size_mismatch", response.headers["location"])

    async def test_stage_2_last_score_does_not_auto_promote_without_stage_finish(self) -> None:
        stage_2 = PlayoffStage(id=50, key="stage_2", title="Stage 2", stage_order=1, stage_size=32)
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage_2])

        with (
            patch.object(web, "apply_playoff_match_results", new=AsyncMock()),
            patch.object(web, "finalize_limited_playoff_stage_if_ready", new=AsyncMock()) as finalize_mock,
        ):
            await web.admin_playoff_score(
                stage_id=50,
                group_number=4,
                placements_list=[str(user_id) for user_id in range(1, 9)],
                placements="",
                db=db,
            )

        finalize_mock.assert_not_awaited()

    async def test_stage_2_last_batch_score_does_not_auto_promote_without_stage_finish(self) -> None:
        stage_2 = PlayoffStage(id=60, key="stage_2", title="Stage 2", stage_order=1, stage_size=32)
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage_2])

        with (
            patch.object(web, "apply_playoff_match_results", new=AsyncMock()),
            patch.object(web, "finalize_limited_playoff_stage_if_ready", new=AsyncMock()) as finalize_mock,
        ):
            await web.admin_playoff_results_batch(
                stage_id=60,
                group_number=4,
                user_ids=[str(user_id) for user_id in range(1, 9)],
                places=[str(place) for place in range(1, 9)],
                db=db,
            )

        finalize_mock.assert_not_awaited()

    async def test_final_stage_allows_score_submission(self) -> None:
        stage_final = PlayoffStage(id=70, key="stage_final", title="Final", stage_order=3, stage_size=8)
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage_final])

        with patch.object(web, "apply_playoff_match_results", new=AsyncMock()) as apply_mock:
            response = await web.admin_playoff_score(
                stage_id=70,
                group_number=1,
                placements_list=[str(user_id) for user_id in range(1, 9)],
                placements="",
                db=db,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=msg_playoff_game_saved", response.headers["location"])
        apply_mock.assert_awaited_once_with(db, 70, [1, 2, 3, 4, 5, 6, 7, 8], group_number=1)

    async def test_final_stage_allows_batch_score_submission(self) -> None:
        stage_final = PlayoffStage(id=71, key="stage_final", title="Final", stage_order=3, stage_size=8)
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage_final])

        with patch.object(web, "apply_playoff_match_results", new=AsyncMock()) as apply_mock:
            response = await web.admin_playoff_results_batch(
                stage_id=71,
                group_number=1,
                user_ids=[str(user_id) for user_id in range(1, 9)],
                places=[str(place) for place in range(1, 9)],
                db=db,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=msg_playoff_game_saved", response.headers["location"])
        apply_mock.assert_awaited_once_with(db, 71, [1, 2, 3, 4, 5, 6, 7, 8], group_number=1)


if __name__ == "__main__":
    unittest.main()
