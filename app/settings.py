from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from the environment with the ``APP_`` prefix."""

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    log_level: str = "INFO"
    validate_responses: bool = True
    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    database_echo: bool = False
