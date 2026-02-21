import unittest

from app.models.tournament import GroupMember, PlayoffParticipant, TournamentGroup
from app.services.tournament import apply_game_results, apply_points_to_playoff_participant


class _FakeScalarsResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


class _FakeSession:
    def __init__(self, group, members):
        self._group = group
        self._members = members
        self._scalar_calls = 0
        self.added_results = []
        self.committed = False

    async def scalar(self, _query):
        self._scalar_calls += 1
        if self._scalar_calls == 1:
            return self._group
        if self._scalar_calls == 2:
            return None
        raise AssertionError("Unexpected scalar() call")

    async def scalars(self, _query):
        return _FakeScalarsResult(self._members)

    def add(self, obj):
        self.added_results.append(obj)

    async def commit(self):
        self.committed = True


class TournamentPointsTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_game_results_uses_points_by_place(self) -> None:
        group = TournamentGroup(id=1, name="Group A", lobby_password="1234", schedule_text="TBD", current_game=1)
        members = [
            GroupMember(group_id=1, user_id=i, seat=i, total_points=0, first_places=0, top4_finishes=0, eighth_places=0, last_game_place=8)
            for i in range(1, 9)
        ]
        session = _FakeSession(group=group, members=members)

        ordered_user_ids = list(range(1, 9))
        await apply_game_results(session, group_id=1, ordered_user_ids=ordered_user_ids)

        points_by_place = {result.place: result.points_awarded for result in session.added_results}
        self.assertEqual(points_by_place[1], 8)
        self.assertEqual(points_by_place[2], 6)
        self.assertEqual(points_by_place[8], 0)

    def test_apply_points_to_playoff_participant_standard_stage(self) -> None:
        place_to_points = {1: 8, 2: 6, 8: 0}
        for place, expected_points in place_to_points.items():
            with self.subTest(place=place):
                participant = PlayoffParticipant(
                    stage_id=1,
                    user_id=1,
                    seed=1,
                    points=0,
                    wins=0,
                    top4_finishes=0,
                    last_place=8,
                    is_eliminated=False,
                )

                apply_points_to_playoff_participant(participant, place=place, scoring_mode="standard")

                self.assertEqual(participant.points, expected_points)


if __name__ == "__main__":
    unittest.main()
