"""Проверяет ручное подтверждение победителя финала в админке."""

import unittest
from unittest.mock import AsyncMock, patch

from app.models.tournament import PlayoffParticipant, PlayoffStage
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
        override_mock.assert_awaited_once_with(db, 102, 1, 5002, note="manual")


if __name__ == "__main__":
    unittest.main()
