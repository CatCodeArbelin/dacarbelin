from app.models.user import User
from app.routers.web import _display_nickname as web_display_nickname
from app.services.tournament_view import _display_nickname as tournament_display_nickname


def _make_user(**overrides) -> User:
    payload = {
        "id": 1,
        "nickname": "ProfileNick",
        "steam_input": "steam_input",
        "steam_id": "123",
        "game_nickname": "GameNick",
        "current_rank": "Immortal",
        "highest_rank": "Immortal",
        "basket": "rook",
    }
    payload.update(overrides)
    return User(**payload)


def test_display_nickname_uses_profile_nickname_in_tournament_view() -> None:
    user = _make_user(
        nickname="SiteNick",
        game_nickname="ArenaNick",
        current_rank="Legend",
        highest_rank="Immortal",
    )

    assert tournament_display_nickname(user, "42") == "SiteNick (Immortal)"
    assert web_display_nickname(user, "42") == "ArenaNick (Immortal)"


def test_display_nickname_fallbacks_for_empty_game_nickname_and_highest_rank() -> None:
    user = _make_user(nickname="SiteNick", game_nickname="  ", highest_rank=" ")

    assert tournament_display_nickname(user, "42") == "SiteNick (-)"
    assert web_display_nickname(user, "42") == "SiteNick (-)"


def test_display_nickname_fallbacks_to_external_value_when_names_empty() -> None:
    user = _make_user(nickname=" ", game_nickname=" ", highest_rank=" ")

    assert tournament_display_nickname(user, "42") == "42 (-)"
    assert web_display_nickname(user, "42") == "42 (-)"


def test_display_nickname_returns_fallback_when_user_missing() -> None:
    assert tournament_display_nickname(None, "42") == "42"
    assert web_display_nickname(None, "42") == "42"
