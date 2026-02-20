TRANSLATIONS = {
    "en": {
        "title": "DAC Tournament",
        "register": "Registration",
        "submit": "Submit",
        "already_registered": "You are already registered",
        "registered_ok": "Registration completed",
        "registration_closed": "Registration closed, tournament started",
    },
    "ru": {
        "title": "DAC Турнир",
        "register": "Регистрация",
        "submit": "Отправить",
        "already_registered": "Вы уже зарегистрированы",
        "registered_ok": "Регистрация завершена",
        "registration_closed": "Регистрация закрыта, турнир начался",
    },
}


def get_lang(lang_cookie: str | None) -> str:
    # Возвращаем язык интерфейса с безопасным фолбэком.
    return lang_cookie if lang_cookie in {"en", "ru"} else "en"


def t(lang: str, key: str) -> str:
    # Получаем перевод по ключу.
    return TRANSLATIONS.get(lang, TRANSLATIONS["en"]).get(key, key)
