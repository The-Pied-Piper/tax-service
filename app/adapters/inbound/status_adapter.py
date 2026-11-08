"""Inbound request adapter for the ``Status`` tag.

Translates wire DTOs (generated Pydantic models) into domain objects, calls the
application port, and maps the result back onto a response DTO. This file is
yours: `service-gen sync` never overwrites it.
"""

from __future__ import annotations

from pydantic import TypeAdapter

from app.application.ports.status_port import StatusPort
from app.generated.models import StatusOutput


class StatusRequestAdapter:
    def __init__(self, service: StatusPort) -> None:
        self._service = service

    async def get_livez(
        self,
    ) -> StatusOutput:
        # TODO: build domain objects from the inputs instead of passing DTOs through.
        result = await self._service.get_livez()
        # TODO: map the domain result onto the response DTO.
        return TypeAdapter(StatusOutput).validate_python(result, from_attributes=True)

    async def get_readyz(
        self,
    ) -> StatusOutput:
        # TODO: build domain objects from the inputs instead of passing DTOs through.
        result = await self._service.get_readyz()
        # TODO: map the domain result onto the response DTO.
        return TypeAdapter(StatusOutput).validate_python(result, from_attributes=True)
