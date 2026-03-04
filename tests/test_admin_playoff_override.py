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

    async def test_override_policy_matches_ui_for_noncanonical_final_stage(self) -> None:
        cases = [
            {"stage_id": 103, "stage_size": 8, "scoring_mode": "standard"},
            {"stage_id": 104, "stage_size": 16, "scoring_mode": "final_22_top1"},
        ]

        for case in cases:
            with self.subTest(case=case):
                stage = PlayoffStage(
                    id=case["stage_id"],
                    key="legacy_custom_final",
                    title="Legacy Final",
                    stage_order=3,
                    stage_size=case["stage_size"],
                    scoring_mode=case["scoring_mode"],
                )
                participant = PlayoffParticipant(stage_id=case["stage_id"], user_id=6001, seed=1, points=22)

                self.assertTrue(web.is_stage_allowed_for_manual_winner(stage))

                db = AsyncMock()
                db.scalar = AsyncMock(side_effect=[stage, participant])

                with patch.object(web, "override_playoff_match_winner", new=AsyncMock()) as override_mock:
                    response = await web.admin_playoff_override(
                        stage_id=case["stage_id"],
                        group_number=1,
                        winner_user_id=6001,
                        note="manual",
                        db=db,
                    )

                self.assertEqual(response.status_code, 303)
                self.assertIn("msg=msg_status_ok", response.headers["location"])
                override_mock.assert_awaited_once_with(db, case["stage_id"], 1, 6001, note="manual")

    async def test_override_rejects_stage_outside_policy_with_specific_reason(self) -> None:
        stage = PlayoffStage(id=105, key="stage_1_4", title="Quarter", stage_order=2, stage_size=16, scoring_mode="standard")

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[stage])

        with patch.object(web, "override_playoff_match_winner", new=AsyncMock()) as override_mock:
            response = await web.admin_playoff_override(
                stage_id=105,
                group_number=1,
                winner_user_id=5005,
                note="",
                db=db,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=msg_operation_failed", response.headers["location"])
        self.assertIn("details=stage_not_final_by_policy", response.headers["location"])
        override_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
