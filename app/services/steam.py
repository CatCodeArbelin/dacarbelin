import re

import httpx

from app.core.config import settings
from app.services.rank import mmr_to_rank

STEAM64_RE = re.compile(r"^7656119\d{10}$")
STEAM_ID2_RE = re.compile(r"^STEAM_0:([01]):(\d+)$", re.IGNORECASE)


async def normalize_steam_id(raw_value: str) -> str | None:
    """Нормализует ввод пользователя до Steam64 через прямой формат, URL vanity и SteamID2."""
    value = raw_value.strip()
    if STEAM64_RE.match(value):
        return value

    if "steamcommunity.com/id/" in value:
        vanity = value.rstrip("/").split("/")[-1]
        resolved = await resolve_vanity(vanity)
        if resolved:
            return resolved

    if "steamcommunity.com/profiles/" in value:
        candidate = value.rstrip("/").split("/")[-1]
        if STEAM64_RE.match(candidate):
            return candidate

    if value.isdigit() and len(value) < 17:
        return str(76561197960265728 + int(value))

    steam_id2 = STEAM_ID2_RE.match(value)
    if steam_id2:
        x = int(steam_id2.group(1))
        y = int(steam_id2.group(2))
        return str(76561197960265728 + y * 2 + x)

    if re.match(r"^[a-zA-Z0-9_\-]+$", value):
        return await resolve_vanity(value)

    return None


async def resolve_vanity(vanity: str) -> str | None:
    # Резолвим vanity id через Steam API если задан ключ.
    if not settings.steam_api_key:
        return None
    url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/"
    params = {"key": settings.steam_api_key, "vanityurl": vanity}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, params=params)
        payload = response.json().get("response", {})
    if payload.get("success") == 1:
        return payload.get("steamid")
    return None


async def fetch_autochess_data(steam_id: str) -> dict:
    """Запрашивает профиль из AutoChess API и вытаскивает нужные поля для регистрации."""
    url = f"http://autochess.ppbizon.com/courier/get/@{steam_id}/"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

    user_info = data.get("user_info", {}).get(steam_id)
    if not user_info:
        raise ValueError("Player not found in AutoChess API")

    season_keys = sorted(
        [k for k in user_info.keys() if k.startswith("mmr_s")],
        key=lambda x: int(x.split("s")[-1]),
        reverse=True,
    )
    max_keys = sorted(
        [k for k in user_info.keys() if k.startswith("max_mmr_s")],
        key=lambda x: int(x.split("s")[-1]),
        reverse=True,
    )

    current_mmr = int(user_info.get(season_keys[0], 0)) if season_keys else 0
    highest_mmr = int(user_info.get(max_keys[0], 0)) if max_keys else current_mmr
    queen_rank = int(user_info.get("queen_rank", 0)) or None

    return {
        "game_nickname": user_info.get("name") or user_info.get("steam_id") or steam_id,
        "current_rank": mmr_to_rank(current_mmr, queen_rank),
        "highest_rank": mmr_to_rank(highest_mmr, queen_rank),
        "raw": user_info,
    }
