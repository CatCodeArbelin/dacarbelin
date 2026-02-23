"""Проверяет ручной перевод участника группы в этап плей-офф."""

import unittest

from app.models.tournament import GroupMember, PlayoffParticipant, PlayoffStage
from app.services.tournament import promote_group_member_to_stage


class _FakeScalarsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, scalar_results, stage_participants):
        self._scalar_results = list(scalar_results)
        self._stage_participants = list(stage_participants)
        self.added = []
        self.committed = False

    async def scalar(self, _query):
        if not self._scalar_results:
            raise AssertionError("Unexpected scalar() call")
        return self._scalar_results.pop(0)

    async def scalars(self, _query):
        return _FakeScalarsResult(self._stage_participants)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


class ManualGroupPromoteTests(unittest.IsolatedAsyncioTestCase):
    async def test_promote_group_member_to_stage_success(self) -> None:
        """Проверяет успешный ручной перевод игрока в следующий этап."""
        group_member = GroupMember(group_id=10, user_id=20, seat=1)
        stage = PlayoffStage(id=30, key="stage_1_4", title="1/4", stage_size=32, stage_order=2)
        existing_participants = [PlayoffParticipant(stage_id=30, user_id=100, seed=4)]
        db = _FakeDB(
            scalar_results=[group_member, stage, None],
            stage_participants=existing_participants,
        )

        await promote_group_member_to_stage(db, group_id=10, user_id=20, target_stage_id=30)

        self.assertTrue(db.committed)
        self.assertEqual(len(db.added), 1)
        added = db.added[0]
        self.assertEqual(added.stage_id, 30)
        self.assertEqual(added.user_id, 20)
        self.assertEqual(added.seed, 5)

    async def test_promote_group_member_to_stage_blocks_duplicates(self) -> None:
        """Проверяет блокировку дубля участника в целевом этапе."""
        group_member = GroupMember(group_id=10, user_id=20, seat=1)
        stage = PlayoffStage(id=30, key="stage_1_4", title="1/4", stage_size=32, stage_order=2)
        duplicate = PlayoffParticipant(stage_id=30, user_id=20, seed=7)
        db = _FakeDB(
            scalar_results=[group_member, stage, duplicate],
            stage_participants=[],
        )

        with self.assertRaises(ValueError) as ctx:
            await promote_group_member_to_stage(db, group_id=10, user_id=20, target_stage_id=30)

        self.assertEqual(str(ctx.exception), "Игрок уже есть в целевом этапе")
        self.assertFalse(db.committed)
        self.assertEqual(db.added, [])


if __name__ == "__main__":
    unittest.main()
