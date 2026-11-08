"""The jurisdictions and tax years a calculation can be run for. Implements JurisdictionsPort.

`service-gen sync` never overwrites this file.
"""

from __future__ import annotations

from app.domain.errors import InvalidArgumentError
from app.domain.take_home import SUPPORTED_JURISDICTIONS, SupportedJurisdiction


class JurisdictionsService:
    async def list_jurisdictions(
        self,
        max_page_size: int | None = None,
        page_token: str | None = None,
    ) -> tuple[SupportedJurisdiction, ...]:
        # One page holds the whole list (max_page_size is an upper bound, and the list is
        # shorter), so there is never a second page to ask for.
        if page_token:
            raise InvalidArgumentError("page_token", "page_token is not a token of this list")
        return SUPPORTED_JURISDICTIONS
