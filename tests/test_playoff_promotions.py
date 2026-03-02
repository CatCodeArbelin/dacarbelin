"""Проверяет правила продвижения участников между стадиями плей-офф."""

import unittest

from app.models.tournament import PlayoffParticipant, PlayoffStage
from app.services.tournament import promote_top_between_stages


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeDB:
    def __init__(self, scalar_items, participants):
        self._scalar_items = list(scalar_items)
        self._participants = participants
        self.added: list[PlayoffParticipant] = []
        self.executed = 0
        self.commits = 0

    async def scalar(self, _statement):
        return self._scalar_items.pop(0)

    async def scalars(self, _statement):
        return _ScalarResult(self._participants)

    async def execute(self, _statement):
        self.executed += 1

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1


class PlayoffPromotionTests(unittest.IsolatedAsyncioTestCase):
    async def test_stage_2_to_stage_3_uses_top4_per_group_and_fills_to_16(self) -> None:
        stage = PlayoffStage(id=10, key="stage_2", title="Stage 2", stage_order=1, stage_size=32)
        next_stage = PlayoffStage(id=20, key="stage_1_4", title="Stage 3", stage_order=2, stage_size=16)

        participants = [
            PlayoffParticipant(stage_id=10, user_id=1, seed=1, points=50, wins=3, top4_finishes=3, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=2, seed=2, points=45, wins=2, top4_finishes=3, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=3, seed=3, points=40, wins=2, top4_finishes=2, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=4, seed=4, points=39, wins=2, top4_finishes=2, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=5, seed=5, points=38, wins=1, top4_finishes=2, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=6, seed=6, points=37, wins=1, top4_finishes=2, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=7, seed=7, points=36, wins=1, top4_finishes=1, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=8, seed=8, points=35, wins=1, top4_finishes=1, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=9, seed=9, points=55, wins=3, top4_finishes=3, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=10, seed=10, points=54, wins=3, top4_finishes=3, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=11, seed=11, points=20, wins=0, top4_finishes=0, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=12, seed=12, points=19, wins=0, top4_finishes=0, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=13, seed=13, points=18, wins=0, top4_finishes=0, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=14, seed=14, points=17, wins=0, top4_finishes=0, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=15, seed=15, points=16, wins=0, top4_finishes=0, top8_finishes=3, last_place=8),
            PlayoffParticipant(stage_id=10, user_id=16, seed=16, points=15, wins=0, top4_finishes=0, top8_finishes=3, last_place=8),
        ]

        db = _FakeDB([stage, next_stage], participants)

        await promote_top_between_stages(db, stage_id=10, top_n=4)

        promoted_user_ids = [participant.user_id for participant in db.added]
        self.assertEqual(len(promoted_user_ids), 16)
        self.assertEqual(promoted_user_ids[:8], [1, 2, 3, 4, 9, 10, 11, 12])
        self.assertTrue(set(promoted_user_ids).issubset({participant.user_id for participant in participants}))
        self.assertEqual(db.executed, 1)
        self.assertEqual(db.commits, 1)

    async def test_stage_1_4_to_final_recreates_participants_with_zero_stats(self) -> None:
        stage = PlayoffStage(id=30, key="stage_1_4", title="Stage 3", stage_order=2, stage_size=16)
        next_stage = PlayoffStage(id=40, key="stage_final", title="Final", stage_order=3, stage_size=8)

        participants = [
            PlayoffParticipant(stage_id=30, user_id=user_id, seed=user_id, points=30 - user_id, wins=2, top4_finishes=2, top8_finishes=3, last_place=8)
            for user_id in range(1, 17)
        ]

        db = _FakeDB([stage, next_stage], participants)

        await promote_top_between_stages(db, stage_id=30, top_n=4)

        self.assertEqual(len(db.added), 8)
        promoted_ids = [participant.user_id for participant in db.added]
        self.assertEqual(promoted_ids, [1, 2, 3, 4, 9, 10, 11, 12])
        for new_participant in db.added:
            self.assertEqual(new_participant.stage_id, 40)
            self.assertEqual(new_participant.points, 0)
            self.assertEqual(new_participant.wins, 0)
            self.assertEqual(new_participant.top4_finishes, 0)
            self.assertEqual(new_participant.top8_finishes, 0)
            self.assertEqual(new_participant.last_place, 8)
            self.assertFalse(new_participant.is_eliminated)

    async def test_promote_top_between_stages_validates_top_n_by_stage_config(self) -> None:
        stage = PlayoffStage(id=50, key="stage_1_4", title="Stage 3", stage_order=2, stage_size=16)
        next_stage = PlayoffStage(id=60, key="stage_final", title="Final", stage_order=3, stage_size=8)

        participants = [
            PlayoffParticipant(stage_id=50, user_id=user_id, seed=user_id, points=30 - user_id, wins=1, top4_finishes=1, top8_finishes=1, last_place=8)
            for user_id in range(1, 17)
        ]

        db = _FakeDB([stage, next_stage], participants)

        with self.assertRaisesRegex(ValueError, "top-4"):
            await promote_top_between_stages(db, stage_id=50, top_n=2)


if __name__ == "__main__":
    unittest.main()
