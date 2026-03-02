"""Проверяет ручной перенос участника между playoff-этапами."""

import unittest
from unittest.mock import AsyncMock, Mock

from app.models.tournament import PlayoffParticipant, PlayoffStage
from app.services.tournament import (
    get_playoff_stages_with_data,
    get_stage_group_number_by_seed,
    move_user_to_stage,
)


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


class MoveUserToStageTests(unittest.IsolatedAsyncioTestCase):
    async def test_move_user_to_stage_assigns_next_seed_and_correct_group(self) -> None:
        """Проверяет ручной перенос с назначением next_seed и корректной группой в целевой стадии."""
        source_participant = PlayoffParticipant(stage_id=10, user_id=100, seed=2, is_eliminated=False)
        target_stage = PlayoffStage(id=20, key="stage_1_4", title="1/4", stage_size=32, stage_order=1)
        target_participants = [
            PlayoffParticipant(stage_id=20, user_id=200, seed=1),
            PlayoffParticipant(stage_id=20, user_id=201, seed=2),
            PlayoffParticipant(stage_id=20, user_id=202, seed=9),
        ]

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[source_participant, target_stage, None])
        db.scalars = AsyncMock(side_effect=[_ScalarResult(target_participants)])
        db.add = Mock()
        db.delete = AsyncMock()

        await move_user_to_stage(db, from_stage_id=10, to_stage_id=20, user_id=100)

        db.delete.assert_awaited_once_with(source_participant)
        db.add.assert_called_once()
        added = db.add.call_args.args[0]
        self.assertEqual(added.stage_id, 20)
        self.assertEqual(added.user_id, 100)
        self.assertEqual(added.seed, 10)

        stages = [
            PlayoffStage(id=10, key="stage_1_8", title="1/8", stage_size=56, stage_order=0, participants=[source_participant]),
            PlayoffStage(
                id=20,
                key="stage_1_4",
                title="1/4",
                stage_size=32,
                stage_order=1,
                participants=[*target_participants, added],
            ),
        ]
        db.scalars = AsyncMock(return_value=_ScalarResult(stages))

        loaded_stages = await get_playoff_stages_with_data(db)
        loaded_target_stage = next(stage for stage in loaded_stages if stage.id == 20)
        moved_participant = next(participant for participant in loaded_target_stage.participants if participant.user_id == 100)

        self.assertEqual(get_stage_group_number_by_seed(moved_participant.seed), 2)
        db.commit.assert_called_once()

    async def test_move_user_to_stage_checks_target_capacity(self) -> None:
        """Проверяет блокировку ручного переноса при переполнении целевого этапа."""
        source_participant = PlayoffParticipant(stage_id=10, user_id=100, seed=2)
        target_stage = PlayoffStage(id=20, key="stage_1_4", title="1/4", stage_size=2, stage_order=1)
        target_participants = [
            PlayoffParticipant(stage_id=20, user_id=200, seed=1),
            PlayoffParticipant(stage_id=20, user_id=201, seed=2),
        ]

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[source_participant, target_stage, None])
        db.scalars = AsyncMock(return_value=_ScalarResult(target_participants))
        db.add = Mock()
        db.delete = AsyncMock()

        with self.assertRaisesRegex(ValueError, "Вместимость целевого этапа превышена"):
            await move_user_to_stage(db, from_stage_id=10, to_stage_id=20, user_id=100)

        db.add.assert_not_called()
        db.delete.assert_not_awaited()
        db.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
