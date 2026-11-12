"""Inbound request adapter for the ``TakeHomeCalculations`` tag.

Translates wire DTOs (generated Pydantic models) into domain objects, calls the
application port, and maps the result back onto a response DTO. This file is
yours: `service-gen sync` never overwrites it.
"""

from __future__ import annotations

from decimal import Decimal

from app.application.ports.take_home_calculations_port import TakeHomeCalculationsPort
from app.domain.take_home import FormTrace as DomainFormTrace
from app.domain.take_home import Rate as DomainRate
from app.domain.take_home import Unit as DomainUnit
from app.generated.models import (
    ComputeTakeHomeCalculationRequest,
    ComputeTakeHomeCalculationResponse,
    FormTrace,
    Placement,
    Rate,
    TraceLine,
    Unit,
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
            unit=_unit(result.unit),
            average_income_tax_rate=_rate(result.average_income_tax_rate),
            marginal_income_tax_rate=_rate(result.marginal_income_tax_rate),
        )
        if result.trace is not None:
            response.trace = [_form_trace(t) for t in result.trace]
        return response


def _form_trace(trace: DomainFormTrace) -> FormTrace:
    return FormTrace(
        form=trace.form,
        name=trace.name or trace.form,
        lines=[
            TraceLine(
                label=line.label,
                name=line.name,
                reference=line.reference,
                amount=str(line.amount),
                text=line.text,
                unit=None if line.unit is None else _unit(line.unit),
            )
            for line in trace.lines
        ],
    )


def _unit(unit: DomainUnit) -> Unit:
    return Unit(
        name=unit.name,
        placement=Placement(unit.placement),
        singular=unit.singular,
        plural=unit.plural,
        spaced=unit.spaced,
        as_percentage=unit.as_percentage,
    )


def _rate(rate: DomainRate) -> Rate:
    return Rate(amount=str(rate.amount), unit=_unit(rate.unit))
