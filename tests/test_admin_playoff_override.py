"""Проверяет ручное подтверждение победителя финала в админке."""

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

from app.models.settings import SiteSetting
from app.models.tournament import PlayoffMatch, PlayoffParticipant, PlayoffStage
from app.routers import web
from app.services.tournament import reset_tournament_cycle_after_finish


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


@asynccontextmanager
async def _noop_transaction():
    yield


class AdminPlayoffOverrideTests(unittest.IsolatedAsyncioTestCase):
    async def test_override_rejects_winner_with_points_below_threshold(self) -> None:
        stage_final = PlayoffStage(id=101, key="stage_final", title="Final", stage_order=3, stage_size=8)
        participant = PlayoffParticipant(stage_id=101, user_id=5001, seed=1, points=21)

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[SiteSetting(key="tournament_finished", value="0"), stage_final, participant])

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
        db.scalar = AsyncMock(side_effect=[SiteSetting(key="tournament_finished", value="0"), stage_final, participant])

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

    async def test_finish_tournament_creates_archive_and_resets_cycle(self) -> None:
        stage_final = PlayoffStage(id=300, key="stage_final", title="Final", stage_order=3, stage_size=8)
        final_match = PlayoffMatch(stage_id=300, group_number=1, state="finished", winner_user_id=7001)
        winner = PlayoffParticipant(stage_id=300, user_id=7001, seed=1, points=30)

        db = AsyncMock()
        db.begin = Mock(return_value=_noop_transaction())
        db.scalars = AsyncMock(return_value=_ScalarResult([stage_final]))
        db.scalar = AsyncMock(side_effect=[final_match, winner])

        with (
            patch.object(web, "snapshot_tournament_archive", new=AsyncMock()) as snapshot_mock,
            patch.object(web, "finalize_tournament_with_winner", new=AsyncMock(return_value="Champion")) as finalize_mock,
            patch.object(web, "reset_tournament_cycle_after_finish", new=AsyncMock()) as reset_mock,
        ):
            response = await web.admin_finish_tournament(db=db)

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=msg_status_ok", response.headers["location"])
        self.assertIn("details=tournament_finished_and_archived%3AChampion", response.headers["location"])
        snapshot_mock.assert_awaited_once()
        finalize_mock.assert_awaited_once_with(db, 7001)
        reset_mock.assert_awaited_once_with(db)

    async def test_finish_tournament_uses_started_final_stage_even_if_other_stage_has_higher_order(self) -> None:
        non_final_started = PlayoffStage(id=410, key="stage_1_4", title="Stage 3", stage_order=99, stage_size=16, is_started=True)
        stage_final = PlayoffStage(id=411, key="stage_final", title="Final", stage_order=4, stage_size=8, is_started=True)
        final_match = PlayoffMatch(stage_id=411, group_number=1, state="finished", winner_user_id=8001)
        winner = PlayoffParticipant(stage_id=411, user_id=8001, seed=1, points=22)

        db = AsyncMock()
        db.begin = Mock(return_value=_noop_transaction())
        db.scalars = AsyncMock(return_value=_ScalarResult([non_final_started, stage_final]))
        db.scalar = AsyncMock(side_effect=[final_match, winner])

        with (
            patch.object(web, "snapshot_tournament_archive", new=AsyncMock()) as snapshot_mock,
            patch.object(web, "finalize_tournament_with_winner", new=AsyncMock(return_value="Winner8001")) as finalize_mock,
            patch.object(web, "reset_tournament_cycle_after_finish", new=AsyncMock()) as reset_mock,
        ):
            response = await web.admin_finish_tournament(db=db)

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=msg_status_ok", response.headers["location"])
        self.assertIn("details=tournament_finished_and_archived%3AWinner8001", response.headers["location"])
        snapshot_mock.assert_awaited_once()
        finalize_mock.assert_awaited_once_with(db, 8001)
        reset_mock.assert_awaited_once_with(db)

    async def test_finish_tournament_requires_finished_final_match(self) -> None:
        stage_final = PlayoffStage(id=301, key="stage_final", title="Final", stage_order=3, stage_size=8)
        final_match = PlayoffMatch(stage_id=301, group_number=1, state="in_progress", winner_user_id=7002)

        db = AsyncMock()
        db.scalars = AsyncMock(return_value=_ScalarResult([stage_final]))
        db.scalar = AsyncMock(side_effect=[final_match])

        response = await web.admin_finish_tournament(db=db)

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=msg_operation_failed", response.headers["location"])
        self.assertIn("details=final_not_finished", response.headers["location"])

    async def test_reset_clears_site_settings_and_tournament_cycle_entities(self) -> None:
        existing_settings = {
            "tournament_started": SiteSetting(key="tournament_started", value="1"),
            "draw_applied": SiteSetting(key="draw_applied", value="1"),
            "tournament_finished": SiteSetting(key="tournament_finished", value="1"),
            "tournament_winner_user_id": SiteSetting(key="tournament_winner_user_id", value="77"),
            "tournament_winner_nickname": SiteSetting(key="tournament_winner_nickname", value="Winner"),
            "registration_open": SiteSetting(key="registration_open", value="0"),
        }

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=list(existing_settings.values()))

        await reset_tournament_cycle_after_finish(db)

        self.assertEqual(db.execute.await_count, 8)
        self.assertEqual(existing_settings["tournament_started"].value, "0")
        self.assertEqual(existing_settings["draw_applied"].value, "0")
        self.assertEqual(existing_settings["tournament_finished"].value, "0")
        self.assertEqual(existing_settings["tournament_winner_user_id"].value, "")
        self.assertEqual(existing_settings["tournament_winner_nickname"].value, "")
        self.assertEqual(existing_settings["registration_open"].value, "1")


    async def test_finish_tournament_rolls_back_on_reset_error(self) -> None:
        stage_final = PlayoffStage(id=500, key="stage_final", title="Final", stage_order=3, stage_size=8)
        final_match = PlayoffMatch(stage_id=500, group_number=1, state="finished", winner_user_id=9001)
        winner = PlayoffParticipant(stage_id=500, user_id=9001, seed=1, points=24)

        db = AsyncMock()
        db.begin = Mock(return_value=_noop_transaction())
        db.scalars = AsyncMock(return_value=_ScalarResult([stage_final]))
        db.scalar = AsyncMock(side_effect=[final_match, winner])

        with (
            patch.object(web, "snapshot_tournament_archive", new=AsyncMock()),
            patch.object(web, "finalize_tournament_with_winner", new=AsyncMock(return_value="Champion")),
            patch.object(web, "reset_tournament_cycle_after_finish", new=AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(db, "rollback", new=AsyncMock()) as rollback_mock,
        ):
            response = await web.admin_finish_tournament(db=db)

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg=msg_operation_failed", response.headers["location"])
        rollback_mock.assert_awaited_once()

if __name__ == "__main__":
    unittest.main()
