import re
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.rank import mmr_to_rank

STEAM64_RE = re.compile(r"^7656119\d{10}$")
STEAM_ID2_RE = re.compile(r"^STEAM_0:([01]):(\d+)$", re.IGNORECASE)
VANITY_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


async def normalize_steam_id(raw_value: str) -> str | None:
    """Нормализует пользовательский Steam идентификатор в Steam64 из числовых и vanity форматов."""
    value = (raw_value or "").strip()
    # Возвращаем корректный Steam64 как есть.
    if STEAM64_RE.match(value):
        return value

    # Пробуем извлечь профиль из полного URL.
    profile_candidate = _extract_profile_id_from_url(value)
    if profile_candidate:
        if STEAM64_RE.match(profile_candidate):
            return profile_candidate
        resolved = await resolve_vanity(profile_candidate)
        if resolved:
            return resolved

    # Конвертируем укороченный цифровой ID в Steam64.
    if value.isdigit() and len(value) < 17:
        return str(76561197960265728 + int(value))

    # Конвертируем старый формат SteamID2 в Steam64.
    steam_id2 = STEAM_ID2_RE.match(value)
    if steam_id2:
        x = int(steam_id2.group(1))
        y = int(steam_id2.group(2))
        return str(76561197960265728 + y * 2 + x)

    # Пытаемся резолвить plain vanity nickname.
    if VANITY_RE.match(value):
        return await resolve_vanity(value)

    return None


async def resolve_vanity(vanity: str) -> str | None:
    # Резолвим vanity через официальный API, если ключ доступен.
    resolved_by_api = await _resolve_vanity_by_steam_api(vanity)
    if resolved_by_api:
        return resolved_by_api

    # Используем публичную профильную страницу как fallback без API-ключа.
    return await _resolve_vanity_by_profile_page(vanity)


async def _resolve_vanity_by_steam_api(vanity: str) -> str | None:
    # Пропускаем официальный API, если ключ не задан.
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


async def _resolve_vanity_by_profile_page(vanity: str) -> str | None:
    # Достаем steamID64 из XML-страницы профиля по vanity.
    profile_url = f"https://steamcommunity.com/id/{vanity}/?xml=1"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        response = await client.get(profile_url)

    if response.status_code != 200:
        return None

    match = re.search(r"<steamID64>(\d{17})</steamID64>", response.text)
    return match.group(1) if match else None


def _extract_profile_id_from_url(value: str) -> str | None:
    # Извлекаем vanity или steam64 из steamcommunity URL.
    if "steamcommunity.com" not in value:
        return None

    parsed = urlparse(value)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None

    kind, profile_id = parts[0].lower(), parts[1]
    if kind in {"id", "profiles"}:
        return profile_id
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
