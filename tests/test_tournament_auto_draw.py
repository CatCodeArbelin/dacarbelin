import unittest

from app.models.tournament import GroupMember, TournamentGroup
from app.models.user import Basket, User
from app.services.tournament import create_auto_draw


class _FakeScalarsResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


class _FakeSession:
    def __init__(self, users):
        self._users = users
        self._scalars_calls = 0
        self.added = []
        self._group_seq = 1
        self.committed = False
        self.rolled_back = False

    async def scalars(self, _query):
        self._scalars_calls += 1
        if self._scalars_calls == 1:
            return _FakeScalarsResult(self._users)
        if self._scalars_calls == 2:
            return _FakeScalarsResult([])
        raise AssertionError("Unexpected scalars() call")

    async def execute(self, _query):
        return None

    def add(self, obj):
        if isinstance(obj, TournamentGroup) and getattr(obj, "id", None) is None:
            obj.id = self._group_seq
            self._group_seq += 1
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def _make_users(count: int) -> list[User]:
    baskets = [
        Basket.QUEEN_TOP.value,
        Basket.QUEEN.value,
        Basket.KING.value,
        Basket.ROOK.value,
        Basket.BISHOP.value,
        Basket.LOW_RANK.value,
    ]
    return [
        User(
            id=idx,
            nickname=f"u{idx}",
            steam_input=f"steam_{idx}",
            steam_id=f"sid_{idx}",
            game_nickname=f"g{idx}",
            current_rank="Rook",
            highest_rank="Queen",
            basket=baskets[(idx - 1) % len(baskets)],
        )
        for idx in range(1, count + 1)
    ]


class TournamentAutoDrawTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_auto_draw_accepts_exact_56_player_grid_7x8(self) -> None:
        session = _FakeSession(users=_make_users(56))

        ok, _message = await create_auto_draw(session)

        self.assertTrue(ok)
        groups = [obj for obj in session.added if isinstance(obj, TournamentGroup)]
        members = [obj for obj in session.added if isinstance(obj, GroupMember)]

        self.assertEqual(len(groups), 7)
        self.assertEqual(len(members), 56)

        members_by_group: dict[int, int] = {}
        for member in members:
            members_by_group[member.group_id] = members_by_group.get(member.group_id, 0) + 1
        self.assertEqual(sorted(members_by_group.values()), [8, 8, 8, 8, 8, 8, 8])

    async def test_create_auto_draw_rejects_if_less_than_56_players(self) -> None:
        session = _FakeSession(users=_make_users(55))

        ok, message = await create_auto_draw(session)

        self.assertFalse(ok)
        self.assertIn("56", message)
        self.assertIn("7x8", message)
        self.assertFalse(session.committed)

    async def test_create_auto_draw_creates_exactly_7_groups_and_56_members(self) -> None:
        session = _FakeSession(users=_make_users(56))

        ok, _message = await create_auto_draw(session)

        self.assertTrue(ok)
        groups = [obj for obj in session.added if isinstance(obj, TournamentGroup)]
        members = [obj for obj in session.added if isinstance(obj, GroupMember)]
        self.assertEqual(len(groups), 7)
        self.assertEqual(len(members), 56)
        self.assertTrue(session.committed)

    async def test_create_auto_draw_with_more_than_56_still_assigns_56(self) -> None:
        session = _FakeSession(users=_make_users(60))

        ok, _message = await create_auto_draw(session)

        self.assertTrue(ok)
        groups = [obj for obj in session.added if isinstance(obj, TournamentGroup)]
        members = [obj for obj in session.added if isinstance(obj, GroupMember)]
        self.assertEqual(len(groups), 7)
        self.assertEqual(len(members), 56)


if __name__ == "__main__":
    unittest.main()
