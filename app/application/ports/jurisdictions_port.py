"""Application port for the ``Jurisdictions`` tag.

The inbound adapter calls this; a service in `application/services` implements it.
`service-gen sync` never overwrites this file.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.take_home import SupportedJurisdiction


class JurisdictionsPort(Protocol):
    async def list_jurisdictions(
        self,
        max_page_size: int | None = None,
        page_token: str | None = None,
    ) -> tuple[SupportedJurisdiction, ...]: ...
