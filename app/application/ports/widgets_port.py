"""Application port for the ``Widgets`` tag.

The inbound adapter calls this; a service in `application/services` implements it.
Replace `Any` with your domain types. `service-gen sync` never overwrites this file.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID


class WidgetsPort(Protocol):
    async def list_widgets(
        self,
        page_size: int | None = None,
        cursor: str | None = None,
    ) -> Any: ...

    async def create_widget(
        self,
        body: Any,
    ) -> Any: ...

    async def get_widget(
        self,
        widget_id: UUID,
    ) -> Any: ...

    async def delete_widget(
        self,
        widget_id: UUID,
    ) -> Any: ...
