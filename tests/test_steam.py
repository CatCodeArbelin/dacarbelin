import asyncio

import pytest

from app.services import steam


def test_normalize_steam_profile_url() -> None:
    result = asyncio.run(steam.normalize_steam_id("https://steamcommunity.com/profiles/76561199677719726/"))
    assert result == "76561199677719726"


def test_normalize_steam_id2() -> None:
    result = asyncio.run(steam.normalize_steam_id("STEAM_0:1:12345"))
    assert result == str(76561197960265728 + 12345 * 2 + 1)


def test_normalize_vanity_url_uses_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(vanity: str) -> str | None:
        return "76561190000000000" if vanity == "DieLikeZombie" else None

    monkeypatch.setattr(steam, "resolve_vanity", fake_resolve)
    result = asyncio.run(steam.normalize_steam_id("https://steamcommunity.com/id/DieLikeZombie/"))
    assert result == "76561190000000000"
