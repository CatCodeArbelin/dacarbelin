"""Загружает и хранит конфигурацию приложения из переменных окружения."""

import logging

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger(__name__)


def parse_twitch_parent_domains_csv(raw_value: str | None) -> list[str]:
    """Нормализует CSV-строку parent-доменов Twitch до списка hostname."""
    if raw_value is None:
        return []

    domains: list[str] = []
    for part in str(raw_value).split(","):
        candidate = part.strip().lower()
        if not candidate:
            continue

        if candidate.startswith(("http://", "https://")):
            logger.warning(
                "Twitch parent domain '%s' contains URL scheme; stripping it to hostname.",
                part.strip(),
            )
            candidate = candidate.split("://", 1)[1]

        normalized = candidate.split("/", 1)[0].split(":", 1)[0].strip()
        if not normalized:
            logger.warning("Invalid twitch_parent_domains entry '%s': empty hostname after normalization.", part.strip())
            continue
        if normalized not in domains:
            domains.append(normalized)

    return domains


class Settings(BaseSettings):
    # Настройки приложения и окружения.
    app_name: str = "DAC Tournament"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True
    database_url: str
    admin_key: str
    steam_api_key: str = ""
    secret_key: str = "change_me"
    twitch_channel: str = "loyrensss"
    twitch_parent_domains: str = ""
    twitch_embed_mode: str = "iframe"
    twitch_autoplay: bool = True
    twitch_muted: bool = False

    @field_validator("twitch_parent_domains", mode="before")
    @classmethod
    def _validate_twitch_parent_domains(cls, value: str | None) -> str:
        domains = parse_twitch_parent_domains_csv(value)
        return ",".join(domains)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
