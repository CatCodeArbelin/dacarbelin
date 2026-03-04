"""Тесты аварийных emergency-операций админки."""

import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.models.tournament import PlayoffMatch, PlayoffParticipant, PlayoffStage
from app.models.settings import SiteSetting
from app.routers import web


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class AdminEmergencyRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_rebuild_stage_dry_run_returns_preview_without_commit(self) -> None:
        request = AsyncMock()
        request.cookies = {}
        db = AsyncMock()
        db.add = Mock()
        stage = PlayoffStage(id=10, key="stage_2", title="S2", stage_order=1, stage_size=32)
        participants = [PlayoffParticipant(stage_id=10, user_id=1, seed=1), PlayoffParticipant(stage_id=10, user_id=2, seed=2)]

        db.scalar = AsyncMock(side_effect=[stage, SiteSetting(key="tournament_finished", value="0")])
        db.scalars = AsyncMock(side_effect=[_ScalarResult(participants)])

        with patch.object(web, "_render_admin_emergency_page", new=AsyncMock(return_value="ok")) as render_mock:
            response = await web.admin_emergency_rebuild_stage(
                request=request,
                stage_id=10,
                user_ids="1,3",
                dry_run=True,
                confirm_final=False,
                db=db,
            )

        self.assertEqual(response, "ok")
        db.commit.assert_not_awaited()
        render_mock.assert_awaited_once()

    async def test_bulk_move_blocked_without_confirmation_after_finish(self) -> None:
        request = AsyncMock()
        request.cookies = {}
        db = AsyncMock()
        db.add = Mock()
        db.scalar = AsyncMock(return_value=SiteSetting(key="tournament_finished", value="1"))

        response = await web.admin_emergency_bulk_move(
            request=request,
            from_stage_id=1,
            to_stage_id=2,
            user_ids="1,2",
            dry_run=False,
            confirm_final=False,
            db=db,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("details=final_locked_require_confirmation", response.headers["location"])

    async def test_diagnostics_reports_stage_integrity_issues(self) -> None:
        request = AsyncMock()
        request.cookies = {}
        db = AsyncMock()
        db.add = Mock()
        stage = PlayoffStage(id=22, key="stage_2", title="S2", stage_order=1, stage_size=8)
        participants = [
            PlayoffParticipant(stage_id=22, user_id=7, seed=1),
            PlayoffParticipant(stage_id=22, user_id=7, seed=2),
        ]
        matches = []

        db.scalars = AsyncMock(side_effect=[_ScalarResult([stage]), _ScalarResult(participants), _ScalarResult(matches)])

        with patch.object(web, "_render_admin_emergency_page", new=AsyncMock(return_value="diag")) as render_mock:
            response = await web.admin_emergency_diagnostics(request=request, dry_run=True, db=db)

        self.assertEqual(response, "diag")
        kwargs = render_mock.await_args.kwargs
        payload = kwargs["preview_payload"]
        self.assertTrue(payload["issues"])
        issue = payload["issues"][0]
        self.assertEqual(issue["stage_id"], 22)
        self.assertIn(7, issue["duplicate_users"])

    async def test_stage_config_dry_run_does_not_modify_matches(self) -> None:
        request = AsyncMock()
        request.cookies = {}
        db = AsyncMock()
        db.add = Mock()
        stage = PlayoffStage(id=11, key="stage_2", title="S2", stage_order=1, stage_size=32)
        participants = [PlayoffParticipant(stage_id=11, user_id=1, seed=10)]
        matches = [PlayoffMatch(stage_id=11, match_number=1, group_number=1)]

        db.scalar = AsyncMock(side_effect=[stage, SiteSetting(key="tournament_finished", value="0")])
        db.scalars = AsyncMock(side_effect=[_ScalarResult(participants), _ScalarResult(matches)])

        with patch.object(web, "_render_admin_emergency_page", new=AsyncMock(return_value="ok")):
            response = await web.admin_emergency_stage_config(
                request=request,
                stage_id=11,
                stage_size=16,
                groups_count=2,
                reseed=True,
                dry_run=True,
                confirm_final=False,
                db=db,
            )

        self.assertEqual(response, "ok")
        self.assertEqual(stage.stage_size, 32)
        self.assertEqual(participants[0].seed, 10)
        db.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
