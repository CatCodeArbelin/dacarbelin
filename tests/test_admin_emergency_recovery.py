"""Тесты аварийных emergency-операций админки."""

import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.models.settings import SiteSetting
from app.models.tournament import PlayoffParticipant
from app.routers import web


class AdminEmergencyRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_replace_player_executes_and_commits(self) -> None:
        request = AsyncMock()
        request.cookies = {}
        db = AsyncMock()
        db.add = Mock()

        participant = PlayoffParticipant(stage_id=11, user_id=100, seed=1)
        reserve_user = Mock(id=200, basket="rook_reserve")

        db.scalar = AsyncMock(
            side_effect=[
                11,
                SiteSetting(key="tournament_finished", value="0"),
                participant,
                reserve_user,
                None,
            ]
        )

        response = await web.admin_emergency_replace_player(
            request=request,
            stage_id=11,
            from_user_id=100,
            reserve_user_id=200,
            confirm_final=False,
            db=db,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(participant.user_id, 200)
        db.commit.assert_awaited_once()

    async def test_playoff_move_executes_and_logs(self) -> None:
        request = AsyncMock()
        request.cookies = {web.ADMIN_SESSION_COOKIE: "root-admin"}
        db = AsyncMock()
        db.add = Mock()
        db.scalar = AsyncMock(
            side_effect=[
                SiteSetting(key="tournament_finished", value="0"),
                1,
                2,
            ]
        )

        with patch.object(web, "move_user_to_stage", new=AsyncMock()) as move_mock:
            response = await web.admin_move_playoff_player(
                request=request,
                from_stage_id=1,
                to_stage_id=2,
                user_id=77,
                confirm_final=False,
                db=db,
            )

        self.assertEqual(response.status_code, 303)
        move_mock.assert_awaited_once_with(db, 1, 2, 77)
        db.add.assert_called_once()
        log_entry = db.add.call_args.args[0]
        self.assertEqual(log_entry.action_type, "playoff_move")
        self.assertFalse(log_entry.dry_run)
        db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
