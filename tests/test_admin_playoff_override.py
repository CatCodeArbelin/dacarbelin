"""Проверяет ручное подтверждение победителя финала в админке."""

import unittest
from unittest.mock import AsyncMock, patch

from app.models.tournament import PlayoffMatch, PlayoffParticipant, PlayoffStage
from app.routers import web


class AdminPlayoffOverrideTests(unittest.IsolatedAsyncioTestCase):
    async def test_override_rejects_winner_with_points_below_threshold(self) -> None:
        stage_final = PlayoffStage(id=101, key="stage_final", title="Final", stage_order=3, stage_size=8)
        participant = PlayoffParticipant(stage_id=101, user_id=5001, seed=1, points=21)

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage_final, participant])

        with patch.object(web, "override_playoff_match_winner", new=AsyncMock()) as override_mock:
            response = await web.admin_playoff_override(
                stage_id=101,
                group_number=1,
                winner_user_id=5001,
                note="",
                db=db,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=msg_operation_failed", response.headers["location"])
        self.assertIn("details=winner_points_below_threshold", response.headers["location"])
        override_mock.assert_not_awaited()

    async def test_override_allows_winner_with_points_at_threshold(self) -> None:
        stage_final = PlayoffStage(id=102, key="stage_final", title="Final", stage_order=3, stage_size=8)
        participant = PlayoffParticipant(stage_id=102, user_id=5002, seed=1, points=22)

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage_final, participant])

        with patch.object(web, "override_playoff_match_winner", new=AsyncMock()) as override_mock:
            response = await web.admin_playoff_override(
                stage_id=102,
                group_number=1,
                winner_user_id=5002,
                note="manual",
                db=db,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=msg_status_ok", response.headers["location"])
        self.assertIn("details=winner_selected", response.headers["location"])
        override_mock.assert_awaited_once_with(db, 102, 1, 5002, note="manual")

    async def test_finish_tournament_creates_archive_and_marks_finished(self) -> None:
        stage_final = PlayoffStage(id=300, key="stage_final", title="Final", stage_order=3, stage_size=8)
        final_match = PlayoffMatch(stage_id=300, group_number=1, state="finished", winner_user_id=7001)
        winner = PlayoffParticipant(stage_id=300, user_id=7001, seed=1, points=30)

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage_final, final_match, winner])

        with (
            patch.object(web, "snapshot_tournament_archive", new=AsyncMock()) as snapshot_mock,
            patch.object(web, "finalize_tournament_with_winner", new=AsyncMock(return_value="Champion")) as finalize_mock,
        ):
            response = await web.admin_finish_tournament(db=db)

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=msg_status_ok", response.headers["location"])
        self.assertIn("details=tournament_finished_and_archived%3AChampion", response.headers["location"])
        snapshot_mock.assert_awaited_once()
        finalize_mock.assert_awaited_once_with(db, 7001)

    async def test_finish_tournament_requires_finished_final_match(self) -> None:
        stage_final = PlayoffStage(id=301, key="stage_final", title="Final", stage_order=3, stage_size=8)
        final_match = PlayoffMatch(stage_id=301, group_number=1, state="in_progress", winner_user_id=7002)

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage_final, final_match])

        response = await web.admin_finish_tournament(db=db)

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=msg_operation_failed", response.headers["location"])
        self.assertIn("details=final_not_finished", response.headers["location"])


if __name__ == "__main__":
    unittest.main()
