"""Inbound request adapter for the ``TakeHomeCalculations`` tag.

Translates wire DTOs (generated Pydantic models) into domain objects, calls the
application port, and maps the result back onto a response DTO. This file is
yours: `service-gen sync` never overwrites it.
"""

from __future__ import annotations

from decimal import Decimal

from app.application.ports.take_home_calculations_port import TakeHomeCalculationsPort
from app.domain.take_home import FormTrace as DomainFormTrace
from app.generated.models import (
    ComputeTakeHomeCalculationRequest,
    ComputeTakeHomeCalculationResponse,
    FormTrace,
    TraceLine,
)


class TakeHomeCalculationsRequestAdapter:
    def __init__(self, service: TakeHomeCalculationsPort) -> None:
        self._service = service

    async def compute_take_home_calculation(
        self,
        body: ComputeTakeHomeCalculationRequest,
    ) -> ComputeTakeHomeCalculationResponse:
        result = await self._service.compute_take_home_calculation(
            jurisdiction_code=body.jurisdiction_code,
            year=body.year,
            salary=Decimal(body.salary),
            language_code=body.language_code if "language_code" in body.model_fields_set else None,
            include_trace=bool(body.include_trace),
        )
        response = ComputeTakeHomeCalculationResponse(
            salary=str(result.salary),
            total_deductions=str(result.total_deductions),
            take_home=str(result.take_home),
            provisional=result.provisional,
        )
        if result.trace is not None:
            response.trace = [_form_trace(t) for t in result.trace]
        return response


def _form_trace(trace: DomainFormTrace) -> FormTrace:
    return FormTrace(
        form=trace.form,
        name=trace.name,
        lines=[
            TraceLine(
                label=line.label,
                name=line.name,
                reference=line.reference,
                amount=str(line.amount),
                text=line.text,
            )
            for line in trace.lines
        ],
    )
