"""Business logic for the ``Widgets`` tag. Implements WidgetsPort.

Unimplemented operations surface as HTTP 501 until you fill them in.
`service-gen sync` never overwrites this file.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID


class WidgetsService:
    async def list_widgets(
        self,
        page_size: int | None = None,
        cursor: str | None = None,
    ) -> Any:
        raise NotImplementedError("listWidgets")

    async def create_widget(
        self,
        body: Any,
    ) -> Any:
        raise NotImplementedError("createWidget")

    async def get_widget(
        self,
        widget_id: UUID,
    ) -> Any:
        raise NotImplementedError("getWidget")

    async def delete_widget(
        self,
        widget_id: UUID,
    ) -> Any:
        raise NotImplementedError("deleteWidget")
