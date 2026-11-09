"""The jurisdictions and tax years a calculation can be run for. Implements JurisdictionsPort.

`service-gen sync` never overwrites this file.
"""

from __future__ import annotations

from app.domain.take_home import SUPPORTED_JURISDICTIONS, SupportedJurisdiction


class JurisdictionsService:
    async def list_jurisdictions(self) -> tuple[SupportedJurisdiction, ...]:
        return SUPPORTED_JURISDICTIONS
