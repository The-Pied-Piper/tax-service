import re
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
        items = value.split(",") if isinstance(value, str) else value
        if not isinstance(items, list):
            return items
        origins: list[str] = []
        for item in items:
            origin = _normalise_origin(str(item))
            if origin and origin not in origins:
                origins.append(origin)
        return origins


_HOST = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?")
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _normalise_origin(raw: str) -> str:
    """`scheme://host[:port]` as a browser sends it (lower case, no default port); "" if blank."""
    text = raw.strip().rstrip("/").lower()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        host, port = parts.hostname, parts.port
    except ValueError:
        host, port = None, None
    if (
        parts.scheme not in _DEFAULT_PORTS
        or host is None
        or not _HOST.fullmatch(host)
        or parts.netloc != host + (f":{port}" if port is not None else "")
        or parts.path
        or parts.query
        or parts.fragment
    ):
        raise ValueError(f"not an origin (want scheme://host[:port], no wildcard): {raw.strip()!r}")
    if port is None or port == _DEFAULT_PORTS[parts.scheme]:
        return f"{parts.scheme}://{host}"
    return f"{parts.scheme}://{host}:{port}"
