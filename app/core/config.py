from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
