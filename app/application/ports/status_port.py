"""Application port for the ``Status`` tag.

The inbound adapter calls this; a service in `application/services` implements it.
Replace `Any` with your domain types. `service-gen sync` never overwrites this file.
"""

from __future__ import annotations

from typing import Any, Protocol


class StatusPort(Protocol):
    async def get_livez(
        self,
    ) -> Any: ...

    async def get_readyz(
        self,
    ) -> Any: ...
