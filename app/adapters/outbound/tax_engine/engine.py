"""Driven adapter: asks tax-engine's take-home service for the deductions of a salary.

The engine decides what a take-home answer is made of: its manifests say where the income tax, each
contribution and the two rates are read, and it sums them. This adapter only asks once (rates and
trace included when wanted) and maps the answer into the domain: the total deductions, the income
tax, the unit the money is in, the trace with the unit of each line, and the two rates, each with
its own unit. A jurisdiction whose engine declares no rates makes the deductions unavailable here,
since the API cannot answer without them yet. The engine is synchronous, so it runs on a worker
thread here; the application only sees an async port. Everything the engine raises is translated
into the port's own errors.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Protocol

from tax_engine import build_take_home
from tax_engine.application.models.take_home import FormTrace as EngineFormTrace
from tax_engine.application.models.take_home import Rate as EngineRate
from tax_engine.application.models.take_home import TakeHomeResult as EngineResult
from tax_engine.application.models.take_home import TraceEntry as EngineTraceEntry
from tax_engine.application.models.take_home import UnitDescription
from tax_engine.application.models.take_home_request import TakeHomeRequest
from tax_engine.domain.errors import DomainError as EngineError
from tax_engine.domain.jurisdiction_code import JurisdictionCode

from app.application.ports.deductions import DeductionsUnavailableError
from app.domain.take_home import Deductions, FormTrace, Rate, TraceEntry, Unit

ENGLISH = "en"


class TakeHome(Protocol):
    """The part of tax-engine's take-home service this adapter uses."""

    def compute(self, request: TakeHomeRequest) -> EngineResult: ...


def _present(text: str | None) -> str | None:
    """The text, or None when there is none (the engine may give nothing or an empty string)."""
    return text or None


def _unit(unit: UnitDescription) -> Unit:
    """The domain unit for the engine's unit description."""
    return Unit(
        name=unit.name,
        placement=unit.placement,
        singular=unit.singular,
        plural=unit.plural,
        spaced=unit.spaced,
        as_percentage=unit.as_percentage,
    )


def _rate(rate: EngineRate | None, who: str, which: str) -> Rate:
    if rate is None:
        raise DeductionsUnavailableError(f"{who}: the engine declares no {which} rate")
    return Rate(rate.value, _unit(rate.unit))


def _entry(entry: EngineTraceEntry) -> TraceEntry:
    return TraceEntry(
        label=entry.label,
        name=_present(entry.name),
        reference=_present(entry.reference),
        amount=entry.amount,  # type: ignore[arg-type]
        text=entry.text,
        unit=None if entry.unit is None else _unit(entry.unit),
    )


def _form(trace: EngineFormTrace) -> FormTrace:
    return FormTrace(
        form=trace.form,
        name=_present(trace.name),
        lines=tuple(_entry(line) for line in trace.lines),
    )


class TaxEngineDeductions:
    """Implements DeductionsCalculator with tax-engine; only English text is available."""

    def __init__(self, engine: TakeHome | None = None) -> None:
        self._engine = build_take_home() if engine is None else engine

    async def calculate(
        self,
        jurisdiction_code: str,
        year: int,
        salary: Decimal,
        language_code: str,
        with_trace: bool,
    ) -> Deductions:
        who = f"{jurisdiction_code} {year}"
        if language_code != ENGLISH:
            raise DeductionsUnavailableError(f"{who}: no trace text in {language_code}")
        request = TakeHomeRequest(
            JurisdictionCode(jurisdiction_code),
            year,
            salary,
            include_rates=True,
            include_trace=with_trace,
        )
        try:
            result = await asyncio.to_thread(self._engine.compute, request)
            return Deductions(
                total_deductions=result.total_deductions,
                income_tax=result.income_tax,
                trace=tuple(_form(t) for t in result.trace or ()),
                unit=_unit(result.unit),
                average_income_tax_rate=_rate(result.average_tax_rate, who, "average"),
                marginal_income_tax_rate=_rate(result.marginal_tax_rate, who, "marginal"),
            )
        except (EngineError, ArithmeticError, KeyError, TypeError, ValueError) as exc:
            raise DeductionsUnavailableError(f"{who}: {type(exc).__name__}") from exc
