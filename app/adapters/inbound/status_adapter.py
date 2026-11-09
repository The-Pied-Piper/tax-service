"""Inbound request adapter for the ``Status`` tag.

Translates wire DTOs (generated Pydantic models) into domain objects, calls the
application port, and maps the result back onto a response DTO. This file is
yours: `service-gen sync` never overwrites it.
"""

from __future__ import annotations

from app.application.ports.status_port import StatusPort
from app.generated.models import StatusOutput


class StatusRequestAdapter:
    def __init__(self, service: StatusPort) -> None:
        self._service = service

    async def get_livez(
        self,
    ) -> StatusOutput:
        result = await self._service.get_livez()
        return StatusOutput(
            status=result.status,
        )

    async def get_readyz(
        self,
    ) -> StatusOutput:
        result = await self._service.get_readyz()
        return StatusOutput(
            status=result.status,
        )
