"""Проверяет консистентность ключей локализации между EN/RU и отсутствие legacy-ключей."""

from app.services.i18n import TRANSLATIONS

LEGACY_TRANSLATION_KEYS = {
    "tournament_promote_rule",
}


def test_i18n_locales_have_same_keyset() -> None:
    en_keys = set(TRANSLATIONS["en"])
    ru_keys = set(TRANSLATIONS["ru"])

    assert en_keys == ru_keys


def test_i18n_locales_do_not_contain_legacy_keys() -> None:
    all_keys = set(TRANSLATIONS["en"]) | set(TRANSLATIONS["ru"])

    assert LEGACY_TRANSLATION_KEYS.isdisjoint(all_keys)
