"""Проверяет ручной перенос участника между playoff-этапами."""

import unittest
from unittest.mock import AsyncMock, Mock

from app.models.tournament import PlayoffMatch, PlayoffParticipant, PlayoffStage, TournamentGroup
from app.models.user import Basket, User
from app.routers import web
from app.services.tournament import (
    get_playoff_stages_with_data,
    get_stage_group_number_by_seed,
    move_user_to_stage,
)
from app.services.tournament_view import build_tournament_tree_vm


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
        db.commit.assert_not_called()

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


class AdminReassignRollbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_reassign_rolls_back_stage_move_when_group_assignment_fails(self) -> None:
        user = User(id=500, nickname="rollback-user", basket=Basket.QUEEN.value)
        source_stage = PlayoffStage(id=40, key="stage_2", title="Stage 2", stage_size=32, stage_order=1)
        target_stage = PlayoffStage(id=41, key="stage_1_4", title="Quarter", stage_size=16, stage_order=2)
        original_membership = PlayoffParticipant(stage_id=40, user_id=500, seed=2)
        memberships = [original_membership]
        db = _ReassignDb(user=user, stages={40: source_stage, 41: target_stage}, memberships=memberships)

        snapshot = [(item.stage_id, item.user_id, item.seed) for item in db.memberships]

        async def fake_move_user_to_stage(db, from_stage_id: int, to_stage_id: int, user_id: int):
            participant = next(item for item in db.memberships if item.user_id == user_id and item.stage_id == from_stage_id)
            participant.stage_id = to_stage_id

        async def fake_rollback():
            db.rollbacks += 1
            db.memberships[:] = [
                PlayoffParticipant(stage_id=stage_id, user_id=member_user_id, seed=seed)
                for stage_id, member_user_id, seed in snapshot
            ]

        original_move = web.move_user_to_stage
        original_find_seed = web._find_group_seed_for_stage
        db.rollback = fake_rollback
        web.move_user_to_stage = fake_move_user_to_stage

        async def fail_group_seed(*args, **kwargs):
            raise ValueError("target_group_is_full")

        web._find_group_seed_for_stage = fail_group_seed
        try:
            response = await web.admin_reassign_user(
                user_id=500,
                target_stage_id="41",
                target_group_number="1",
                replace_from_user_id="",
                quick_move=None,
                reassign_action="move_stage",
                db=db,
            )
        finally:
            web.move_user_to_stage = original_move
            web._find_group_seed_for_stage = original_find_seed

        self.assertEqual(response.status_code, 303)
        self.assertIn("msg_operation_failed", response.headers["location"])
        self.assertIn("details=target_group_is_full", response.headers["location"])
        rolled_back_membership = next(item for item in db.memberships if item.user_id == 500)
        self.assertEqual(rolled_back_membership.stage_id, 40)



if __name__ == "__main__":
    unittest.main()


class _ReassignDb:
    def __init__(self, *, user: User, stages: dict[int, PlayoffStage], memberships: list[PlayoffParticipant]):
        self.user = user
        self.stages = stages
        self.memberships = memberships
        self.commits = 0
        self.rollbacks = 0

    async def get(self, model, key):
        if model is User and key == self.user.id:
            return self.user
        if model is PlayoffStage:
            return self.stages.get(key)
        return None

    @staticmethod
    def _int_params(statement) -> list[int]:
        try:
            params = statement.compile().params
        except Exception:
            return []
        return [value for value in params.values() if isinstance(value, int)]

    async def scalars(self, statement):
        sql = str(statement)
        int_params = self._int_params(statement)
        if "FROM playoff_participants" in sql and "playoff_participants.user_id" in sql:
            return _ScalarResult([m for m in self.memberships if m.user_id == self.user.id])
        if "FROM playoff_participants" in sql and "playoff_participants.stage_id" in sql:
            stage_id = int_params[0] if int_params else None
            return _ScalarResult([m for m in self.memberships if stage_id is not None and m.stage_id == stage_id])
        return _ScalarResult([])

    async def scalar(self, statement):
        sql = str(statement)
        if "FROM group_members" in sql:
            return None
        if "FROM playoff_participants" in sql:
            int_params = self._int_params(statement)
            stage_id = int_params[0] if int_params else None
            user_id = int_params[1] if len(int_params) > 1 else self.user.id
            if stage_id is None:
                return None
            return next((m for m in self.memberships if m.stage_id == stage_id and m.user_id == user_id), None)
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class AdminReassignFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_reassign_route_updates_stage_and_group_seed(self) -> None:
        user = User(id=300, nickname="route-user", basket=Basket.QUEEN.value)
        stage_2 = PlayoffStage(id=20, key="stage_2", title="Stage 2", stage_size=32, stage_order=1)
        stage_quarter = PlayoffStage(id=30, key="stage_1_4", title="Quarter", stage_size=16, stage_order=2)
        memberships = [
            PlayoffParticipant(stage_id=20, user_id=300, seed=2),
            PlayoffParticipant(stage_id=30, user_id=400, seed=9),
        ]
        db = _ReassignDb(user=user, stages={20: stage_2, 30: stage_quarter}, memberships=memberships)

        async def fake_move_user_to_stage(db, from_stage_id: int, to_stage_id: int, user_id: int):
            participant = next(item for item in db.memberships if item.user_id == user_id and item.stage_id == from_stage_id)
            participant.stage_id = to_stage_id

        original_move = web.move_user_to_stage
        web.move_user_to_stage = fake_move_user_to_stage
        try:
            response = await web.admin_reassign_user(
                user_id=300,
                target_stage_id="30",
                target_group_number="2",
                replace_from_user_id="",
                quick_move=None,
                reassign_action="move_stage",
                db=db,
            )
        finally:
            web.move_user_to_stage = original_move

        self.assertEqual(response.status_code, 303)
        moved = next(item for item in db.memberships if item.user_id == 300)
        self.assertEqual(moved.stage_id, 30)
        self.assertEqual(get_stage_group_number_by_seed(moved.seed), 2)

    async def test_tournament_tree_uses_new_position_after_reassign(self) -> None:
        user = User(id=301, nickname="viewer-user", basket=Basket.QUEEN.value)
        stage_2 = PlayoffStage(id=21, key="stage_2", title="Stage 2", stage_size=32, stage_order=1)
        stage_quarter = PlayoffStage(id=31, key="stage_1_4", title="Quarter", stage_size=16, stage_order=2)
        memberships = [
            PlayoffParticipant(stage_id=21, user_id=301, seed=3),
            PlayoffParticipant(stage_id=31, user_id=401, seed=1),
            PlayoffParticipant(stage_id=31, user_id=402, seed=2),
            PlayoffParticipant(stage_id=31, user_id=403, seed=3),
            PlayoffParticipant(stage_id=31, user_id=404, seed=4),
            PlayoffParticipant(stage_id=31, user_id=405, seed=5),
            PlayoffParticipant(stage_id=31, user_id=406, seed=6),
            PlayoffParticipant(stage_id=31, user_id=407, seed=7),
            PlayoffParticipant(stage_id=31, user_id=408, seed=8),
        ]
        db = _ReassignDb(user=user, stages={21: stage_2, 31: stage_quarter}, memberships=memberships)

        async def fake_move_user_to_stage(db, from_stage_id: int, to_stage_id: int, user_id: int):
            participant = next(item for item in db.memberships if item.user_id == user_id and item.stage_id == from_stage_id)
            participant.stage_id = to_stage_id

        original_move = web.move_user_to_stage
        web.move_user_to_stage = fake_move_user_to_stage
        try:
            await web.admin_reassign_user(
                user_id=301,
                target_stage_id="31",
                target_group_number="2",
                replace_from_user_id="",
                quick_move=None,
                reassign_action="move_stage",
                db=db,
            )
        finally:
            web.move_user_to_stage = original_move

        stage_2.participants = [item for item in db.memberships if item.stage_id == 21]
        stage_quarter.participants = [item for item in db.memberships if item.stage_id == 31]
        for participant in [*stage_2.participants, *stage_quarter.participants]:
            participant.points = participant.points or 0
            participant.wins = participant.wins or 0
            participant.top4_finishes = participant.top4_finishes or 0
            participant.top8_finishes = participant.top8_finishes or 0
            participant.last_place = participant.last_place or 8

        stage_2.matches = [PlayoffMatch(stage_id=21, match_number=1, group_number=1, game_number=1, schedule_text="TBD", lobby_password="0000")]
        stage_quarter.matches = [
            PlayoffMatch(stage_id=31, match_number=1, group_number=1, game_number=1, schedule_text="TBD", lobby_password="0000"),
            PlayoffMatch(stage_id=31, match_number=2, group_number=2, game_number=1, schedule_text="TBD", lobby_password="0000"),
        ]

        vm = build_tournament_tree_vm(
            groups=[TournamentGroup(id=1, name="A", stage="group_stage", current_game=1, is_started=False)],
            playoff_stages=[stage_2, stage_quarter],
            user_by_id={301: user},
            direct_invite_ids=[],
            active_stage_key="stage_1_4",
        )

        quarter_stage = next(stage for stage in vm["stages"] if stage["key"] == "stage_1_4")
        second_match = next(match for match in quarter_stage["matches"] if match["label"] == "B")
        self.assertTrue(any(participant["user_id"] == 301 for participant in second_match["participants"]))
