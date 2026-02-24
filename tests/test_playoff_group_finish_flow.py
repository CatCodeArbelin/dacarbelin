"""Проверяет автопереход стадии после завершения активных групп."""

import unittest
from unittest.mock import AsyncMock, patch

from app.models.tournament import PlayoffMatch, PlayoffParticipant, PlayoffStage
from app.routers import web


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class PlayoffGroupFinishFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_stage_is_finished_by_active_groups_only(self) -> None:
        stage = PlayoffStage(id=10, key="stage_1_8", title="Stage 1/8", stage_order=0)
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
        promote_mock.assert_awaited_once_with(db, 10, 4)
        start_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
