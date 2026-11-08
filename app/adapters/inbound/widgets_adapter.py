"""Inbound request adapter for the ``Widgets`` tag.

Translates wire DTOs (generated Pydantic models) into domain objects, calls the
application port, and maps the result back onto a response DTO. This file is
yours: `service-gen sync` never overwrites it.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import TypeAdapter

from app.application.ports.widgets_port import WidgetsPort
from app.generated.models import CreateWidgetRequest, Widget, WidgetPage


class WidgetsRequestAdapter:
    def __init__(self, service: WidgetsPort) -> None:
        self._service = service

    async def list_widgets(
        self,
        page_size: int | None = None,
        cursor: str | None = None,
    ) -> WidgetPage:
        # TODO: build domain objects from the inputs instead of passing DTOs through.
        result = await self._service.list_widgets(page_size=page_size, cursor=cursor)
        # TODO: map the domain result onto the response DTO.
        return TypeAdapter(WidgetPage).validate_python(result, from_attributes=True)

    async def create_widget(
        self,
        body: CreateWidgetRequest,
    ) -> Widget:
        # TODO: build domain objects from the inputs instead of passing DTOs through.
        result = await self._service.create_widget(body=body)
        # TODO: map the domain result onto the response DTO.
        return TypeAdapter(Widget).validate_python(result, from_attributes=True)

    async def get_widget(
        self,
        widget_id: UUID,
    ) -> Widget:
        # TODO: build domain objects from the inputs instead of passing DTOs through.
        result = await self._service.get_widget(widget_id=widget_id)
        # TODO: map the domain result onto the response DTO.
        return TypeAdapter(Widget).validate_python(result, from_attributes=True)

    async def delete_widget(
        self,
        widget_id: UUID,
    ) -> None:
        # TODO: build domain objects from the inputs instead of passing DTOs through.
        await self._service.delete_widget(widget_id=widget_id)
