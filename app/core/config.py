"""Загружает и хранит конфигурацию приложения из переменных окружения."""

import logging

from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger(__name__)



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
    tiny_mce_api_key: str = "no-api-key"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
