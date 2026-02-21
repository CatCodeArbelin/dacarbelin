"""Проверяет интеграцию сервиса Steam и обработку ответов API."""

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


def test_fetch_autochess_data_uses_steam_summary_nickname_when_name_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    steam_id = "76561198000000000"

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict, text: str = "") -> None:
            self.status_code = status_code
            self._payload = payload
            self.text = text

        def json(self) -> dict:
            return self._payload

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError("HTTP error")

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str, params: dict | None = None) -> FakeResponse:
            if "autochess.ppbizon.com" in url:
                return FakeResponse(
                    status_code=200,
                    payload={
                        "user_info": {
                            steam_id: {
                                "steam_id": steam_id,
                                "mmr_s15": 1900,
                                "max_mmr_s15": 2100,
                            }
                        }
                    },
                )

            if "GetPlayerSummaries" in url:
                assert params == {"key": "test-key", "steamids": steam_id}
                return FakeResponse(
                    status_code=200,
                    payload={
                        "response": {
                            "players": [{"personaname": "Readable Steam Nick"}],
                        }
                    },
                )

            raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(steam.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(steam.settings, "steam_api_key", "test-key")

    result = asyncio.run(steam.fetch_autochess_data(steam_id))

    assert result["game_nickname"] == "Readable Steam Nick"
