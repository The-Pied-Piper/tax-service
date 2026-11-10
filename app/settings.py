from typing import Annotated
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from the environment with the ``APP_`` prefix."""

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    log_level: str = "INFO"
    validate_responses: bool = True
    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    database_echo: bool = False
    # Website origins allowed to call the API from a browser, as a comma-separated list, e.g.
    # "https://aftertaxlens.com,http://localhost:5173". Empty means no cross-origin access.
    cors_allowed_origins: Annotated[list[str], NoDecode] = []

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: object) -> object:
        """Split, normalise and check origins; a typo fails at startup, not in the browser."""
        if not isinstance(value, str):
            return value
        origins = []
        for item in value.split(","):
            origin = item.strip().rstrip("/").lower()
            if not origin:
                continue
            parts = urlsplit(origin)
            if parts.scheme not in ("http", "https") or not parts.netloc or parts.path:
                raise ValueError(f"not an origin (want scheme://host[:port]): {item.strip()!r}")
            origins.append(origin)
        return origins
