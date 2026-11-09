"""Application port for the ``Status`` tag.

The inbound adapter calls this; a service in `application/services` implements it.
`service-gen sync` never overwrites this file.
"""

from __future__ import annotations

from typing import Protocol

from app.application.ports.health import Health


class StatusPort(Protocol):
    async def get_livez(
        self,
    ) -> Health: ...

    async def get_readyz(
        self,
    ) -> Health: ...
