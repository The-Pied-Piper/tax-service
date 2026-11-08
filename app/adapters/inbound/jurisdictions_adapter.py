"""Inbound request adapter for the ``Jurisdictions`` tag.

Translates wire DTOs (generated Pydantic models) into domain objects, calls the
application port, and maps the result back onto a response DTO. This file is
yours: `service-gen sync` never overwrites it.
"""

from __future__ import annotations

from app.application.ports.jurisdictions_port import JurisdictionsPort
from app.generated.models import Jurisdiction, JurisdictionYear, ListJurisdictionsResponse


class JurisdictionsRequestAdapter:
    def __init__(self, service: JurisdictionsPort) -> None:
        self._service = service

    async def list_jurisdictions(
        self,
        max_page_size: int | None = None,
        page_token: str | None = None,
    ) -> ListJurisdictionsResponse:
        result = await self._service.list_jurisdictions(
            max_page_size=max_page_size, page_token=page_token
        )
        return ListJurisdictionsResponse(
            jurisdictions=[
                Jurisdiction(
                    code=j.code,
                    years=[
                        JurisdictionYear(year=y.year, provisional=y.provisional) for y in j.years
                    ],
                )
                for j in result
            ],
            next_page_token="",
        )
