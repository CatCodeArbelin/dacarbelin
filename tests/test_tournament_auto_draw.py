"""Проверяет автоматическую жеребьёвку и формирование пар в турнире."""

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
    def __init__(self, users, profile_key: str = "56"):
        self._users = users
        self._profile_key = profile_key
        self._scalars_calls = 0
        self.added = []
        self._group_seq = 1
        self.committed = False
        self.rolled_back = False

    async def scalars(self, query):
        query_text = str(query)
        if "site_settings" in query_text:
            return _FakeScalarsResult([type("_Setting", (), {"value": self._profile_key})()])

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


def _make_users_with_reserve_mix() -> list[User]:
    baskets = [
        Basket.QUEEN.value,
        Basket.QUEEN_RESERVE.value,
        Basket.KING.value,
        Basket.KING_RESERVE.value,
        Basket.ROOK.value,
        Basket.ROOK_RESERVE.value,
        Basket.BISHOP.value,
        Basket.BISHOP_RESERVE.value,
        Basket.LOW_RANK.value,
        Basket.LOW_RANK_RESERVE.value,
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
        for idx in range(1, 57)
    ]


def _make_users_with_invited() -> list[User]:
    users = _make_users(56)
    users.extend(
        [
            User(
                id=1000 + idx,
                nickname=f"inv{idx}",
                steam_input=f"inv_steam_{idx}",
                steam_id=f"inv_sid_{idx}",
                game_nickname=f"inv_g{idx}",
                current_rank="Queen",
                highest_rank="Queen",
                basket=Basket.INVITED.value,
            )
            for idx in range(1, 5)
        ]
    )
    return users


class _FailingAddSession(_FakeSession):
    def __init__(self, users, fail_on_add_index: int | None = None, fail_on_flush: bool = False, fail_exception: type[Exception] = ValueError):
        super().__init__(users)
        self._fail_on_add_index = fail_on_add_index
        self._fail_on_flush = fail_on_flush
        self._add_calls = 0
        self._fail_exception = fail_exception

    def add(self, obj):
        self._add_calls += 1
        super().add(obj)
        if self._fail_on_add_index is not None and self._add_calls == self._fail_on_add_index:
            raise self._fail_exception("Synthetic add failure")

    async def flush(self):
        if self._fail_on_flush:
            raise self._fail_exception("Synthetic flush failure")
        await super().flush()


class TournamentAutoDrawTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_auto_draw_accepts_exact_56_player_grid_7x8(self) -> None:
        """Проверяет граничный сценарий `test_create_auto_draw_accepts_exact_56_player_grid_7x8`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_auto_draw.py -q` и `pytest tests/test_tournament_auto_draw.py -k "test_create_auto_draw_accepts_exact_56_player_grid_7x8" -q`."""
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

    async def test_create_auto_draw_accepts_48_profile_grid_6x8(self) -> None:
        session = _FakeSession(users=_make_users(48), profile_key="48")

        ok, _message = await create_auto_draw(session)

        self.assertTrue(ok)
        groups = [obj for obj in session.added if isinstance(obj, TournamentGroup)]
        members = [obj for obj in session.added if isinstance(obj, GroupMember)]
        self.assertEqual(len(groups), 6)
        self.assertEqual(len(members), 48)

    async def test_create_auto_draw_rejects_if_less_than_56_players(self) -> None:
        """Проверяет негативный сценарий `test_create_auto_draw_rejects_if_less_than_56_players`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_auto_draw.py -q` и `pytest tests/test_tournament_auto_draw.py -k "test_create_auto_draw_rejects_if_less_than_56_players" -q`."""
        session = _FakeSession(users=_make_users(55))

        ok, message = await create_auto_draw(session)

        self.assertFalse(ok)
        self.assertIn("56", message)
        self.assertIn("7x8", message)
        self.assertFalse(session.committed)

    async def test_create_auto_draw_creates_exactly_7_groups_and_56_members(self) -> None:
        """Проверяет граничный сценарий `test_create_auto_draw_creates_exactly_7_groups_and_56_members`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_auto_draw.py -q` и `pytest tests/test_tournament_auto_draw.py -k "test_create_auto_draw_creates_exactly_7_groups_and_56_members" -q`."""
        session = _FakeSession(users=_make_users(56))

        ok, _message = await create_auto_draw(session)

        self.assertTrue(ok)
        groups = [obj for obj in session.added if isinstance(obj, TournamentGroup)]
        members = [obj for obj in session.added if isinstance(obj, GroupMember)]
        self.assertEqual(len(groups), 7)
        self.assertEqual(len(members), 56)
        self.assertTrue(session.committed)

    async def test_create_auto_draw_with_more_than_56_still_assigns_56(self) -> None:
        """Проверяет граничный сценарий `test_create_auto_draw_with_more_than_56_still_assigns_56`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_auto_draw.py -q` и `pytest tests/test_tournament_auto_draw.py -k "test_create_auto_draw_with_more_than_56_still_assigns_56" -q`."""
        session = _FakeSession(users=_make_users(60))

        ok, _message = await create_auto_draw(session)

        self.assertTrue(ok)
        groups = [obj for obj in session.added if isinstance(obj, TournamentGroup)]
        members = [obj for obj in session.added if isinstance(obj, GroupMember)]
        self.assertEqual(len(groups), 7)
        self.assertEqual(len(members), 56)

    async def test_create_auto_draw_accepts_reserve_baskets_for_7x8(self) -> None:
        """Проверяет позитивный сценарий `test_create_auto_draw_accepts_reserve_baskets_for_7x8`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_auto_draw.py -q` и `pytest tests/test_tournament_auto_draw.py -k "test_create_auto_draw_accepts_reserve_baskets_for_7x8" -q`."""
        session = _FakeSession(users=_make_users_with_reserve_mix())

        ok, _message = await create_auto_draw(session)

        self.assertTrue(ok)
        groups = [obj for obj in session.added if isinstance(obj, TournamentGroup)]
        members = [obj for obj in session.added if isinstance(obj, GroupMember)]
        self.assertEqual(len(groups), 7)
        self.assertEqual(len(members), 56)
        self.assertTrue(session.committed)

    async def test_create_auto_draw_excludes_invited_from_group_stage(self) -> None:
        """Проверяет негативный сценарий `test_create_auto_draw_excludes_invited_from_group_stage`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_auto_draw.py -q` и `pytest tests/test_tournament_auto_draw.py -k "test_create_auto_draw_excludes_invited_from_group_stage" -q`."""
        session = _FakeSession(users=_make_users_with_invited())

        ok, _message = await create_auto_draw(session)

        self.assertTrue(ok)
        members = [obj for obj in session.added if isinstance(obj, GroupMember)]
        invited_ids = {user.id for user in session._users if user.basket == Basket.INVITED.value}
        member_ids = {member.user_id for member in members}

        self.assertEqual(len(members), 56)
        self.assertTrue(invited_ids.isdisjoint(member_ids))

    async def test_create_auto_draw_rolls_back_when_add_fails_after_partial_assignments(self) -> None:
        """Проверяет негативный сценарий `test_create_auto_draw_rolls_back_when_add_fails_after_partial_assignments`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_auto_draw.py -q` и `pytest tests/test_tournament_auto_draw.py -k "test_create_auto_draw_rolls_back_when_add_fails_after_partial_assignments" -q`."""
        session = _FailingAddSession(users=_make_users(56), fail_on_add_index=10)

        ok, message = await create_auto_draw(session)

        self.assertFalse(ok)
        self.assertIn("Synthetic add failure", message)
        self.assertTrue(session.rolled_back)
        self.assertFalse(session.committed)

    async def test_create_auto_draw_rolls_back_with_status_when_flush_fails_after_groups_created(self) -> None:
        """Проверяет негативный сценарий `test_create_auto_draw_rolls_back_with_status_when_flush_fails_after_groups_created`.
        Важно для бизнес-логики: защищает ключевой турнирный/интеграционный поток от регрессий.
        Запуск: `pytest tests/test_tournament_auto_draw.py -q` и `pytest tests/test_tournament_auto_draw.py -k "test_create_auto_draw_rolls_back_with_status_when_flush_fails_after_groups_created" -q`."""
        session = _FailingAddSession(users=_make_users(56), fail_on_flush=True)

        ok, message = await create_auto_draw(session)

        self.assertFalse(ok)
        self.assertIn("Synthetic flush failure", message)
        self.assertTrue(session.rolled_back)
        self.assertFalse(session.committed)


if __name__ == "__main__":
    unittest.main()
