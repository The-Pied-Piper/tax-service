"""Driven adapter: asks tax-engine for the deductions of a salary.

It only maps each deduction item the application asks for to the engine's form and kind, and reads
the figure off the worksheet: CPP (base and enhanced) and CPP2 from Schedule 8, EI from T2204
"premiums deducted" and income tax as T1 line 167 (federal and provincial tax less credits and
benefits). The average and marginal income tax rates are read the same way off the jurisdiction's
own return (the form and kinds are per-jurisdiction policy here), each with its own unit; a rate
without a unit makes the deductions unavailable. It also reads the unit of each trace row off the
worksheet, and the unit the figures are in: they must all have the same one (the rates do not take
part), else the deductions are unavailable. What "total deductions" is made of is decided by the
domain. The engine is synchronous, so it runs on a worker thread here; the application only sees an
async port. Everything the engine raises is translated into the port's own errors.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Protocol

from tax_engine import build_tax_computation
from tax_engine.adapters.inbound.trace_english import EnglishTraceRenderer
from tax_engine.adapters.inbound.trace_english.unit_text import EnglishUnitTextRegistry
from tax_engine.domain.artifact import Artifact
from tax_engine.domain.errors import DomainError as EngineError
from tax_engine.domain.jurisdiction_code import JurisdictionCode
from tax_engine.domain.trace import TraceLine
from tax_engine.domain.unit import Unit as EngineUnit
from tax_engine.domain.worksheet import Worksheet
from tax_engine.jurisdictions.ca.catalog.income import EMPLOYMENT_INCOME
from tax_engine.registrations import artifact_kinds

from app.application.ports.deductions import DeductionsUnavailableError
from app.domain.take_home import DeductionFigure, Deductions, FormTrace, Rate, TraceEntry, Unit

ENGLISH = "en"

# Each deduction item to the engine's (form, kind) that holds its figure.
FIGURES = {
    "cpp_base": ("ca/schedule_8", "ca/schedule_8_cpp_base_contributions_on_return"),
    "cpp_enhanced": ("ca/schedule_8", "ca/cpp_part_3_line_12"),
    "cpp2": ("ca/schedule_8", "ca/cpp_part_3_line_22"),
    "ei": ("ca/t2204", "ca/t2204_premiums_deducted"),
    "income_tax": ("ca/t1_tax_and_credits", "ca/refund_or_balance_owing"),
}
# Each jurisdiction's engine (form, kind) of the average and of the marginal income tax rate.
AVERAGE_RATES = {
    "CA-ON": ("ca-on/return", "ca-on/average_income_tax_rate"),
    "CA-AB": ("ca-ab/return", "ca-ab/average_income_tax_rate"),
}
MARGINAL_RATES = {
    "CA-ON": ("ca-on/return", "ca-on/marginal_tax_rate"),
    "CA-AB": ("ca-ab/return", "ca-ab/marginal_tax_rate"),
}


class Engine(Protocol):
    """The part of tax-engine's computation service this adapter uses."""

    def compute(
        self, code: JurisdictionCode, tax_year: int, *inputs: Artifact[Decimal]
    ) -> Mapping[str, Sequence[Worksheet]]: ...


class Renderer(Protocol):
    """The part of tax-engine's trace renderer this adapter uses."""

    def render(self, line: TraceLine, printed: Worksheet | None = None) -> str: ...


def _present(text: str | None) -> str | None:
    """The text, or None when there is none (the engine may give nothing or an empty string)."""
    return text or None


def _unit(unit: EngineUnit) -> Unit:
    """The domain unit for the engine's, with its English text."""
    text = EnglishUnitTextRegistry.shared().for_unit(unit)
    return Unit(
        name=unit.identifier,
        placement=text.placement.value,
        singular=text.singular,
        plural=text.plural,
        spaced=text.spaced,
        as_percentage=text.as_percentage,
    )


def _line_unit(sheet: Worksheet, line: TraceLine) -> Unit | None:
    """The unit of the figure the line is about; None if it is about none or it has none."""
    unit = None if line.label is None else sheet.unit(line.label)
    return None if unit is None else _unit(unit)


class TaxEngineDeductions:
    """Implements DeductionsCalculator with tax-engine; only English text is available."""

    def __init__(self, engine: Engine | None = None, renderer: Renderer | None = None) -> None:
        self._engine = build_tax_computation() if engine is None else engine
        self._kinds = artifact_kinds()
        self._renderer = EnglishTraceRenderer() if renderer is None else renderer

    async def calculate(
        self,
        jurisdiction_code: str,
        year: int,
        salary: Decimal,
        language_code: str,
        items: tuple[str, ...],
        with_trace: bool,
    ) -> Deductions:
        if language_code != ENGLISH:
            raise DeductionsUnavailableError(
                f"{jurisdiction_code} {year}: no trace text in {language_code}"
            )
        try:
            return await asyncio.to_thread(
                self._calculate, jurisdiction_code, year, salary, items, with_trace
            )
        except (EngineError, ArithmeticError, KeyError, TypeError, ValueError) as exc:
            raise DeductionsUnavailableError(
                f"{jurisdiction_code} {year}: {type(exc).__name__}"
            ) from exc

    def _calculate(
        self,
        jurisdiction_code: str,
        year: int,
        salary: Decimal,
        items: tuple[str, ...],
        with_trace: bool,
    ) -> Deductions:
        sheets = self._engine.compute(
            JurisdictionCode(jurisdiction_code), year, Artifact(EMPLOYMENT_INCOME, salary)
        )

        units: list[EngineUnit | None] = []

        def read(form: str, kind: str) -> tuple[Decimal, EngineUnit | None]:
            (sheet,) = sheets[form]
            artifact = sheet.get(self._kinds.kind(kind))
            value = artifact.value
            if not isinstance(value, Decimal):
                raise TypeError(f"{kind} is not a decimal")
            return value, artifact.unit

        def figure(item: str) -> Decimal:
            value, unit = read(*FIGURES[item])
            units.append(unit)
            return value

        def rate(form_and_kind: tuple[str, str]) -> Rate:
            value, unit = read(*form_and_kind)
            if unit is None:
                raise DeductionsUnavailableError(
                    f"{jurisdiction_code} {year}: {form_and_kind[1]} has no unit"
                )
            return Rate(value, _unit(unit))

        trace: list[FormTrace] = []
        if with_trace:
            for form, form_sheets in sheets.items():
                for sheet in form_sheets:
                    lines = tuple(
                        TraceEntry(
                            label=line.label,
                            name=_present(None if line.label is None else sheet.title(line.label)),
                            reference=_present(
                                None if line.label is None else sheet.reference(line.label)
                            ),
                            amount=line.amount,
                            text=self._renderer.render(line, sheet),
                            unit=_line_unit(sheet, line),
                        )
                        for line in sheet.trace
                    )
                    trace.append(FormTrace(form=form, name=_present(sheet.form_title), lines=lines))
        figures = tuple(DeductionFigure(item, figure(item)) for item in items)
        unit = units[0] if units else None
        if unit is None or any(other != unit for other in units):
            raise DeductionsUnavailableError(
                f"{jurisdiction_code} {year}: the figures do not share one unit"
            )
        return Deductions(
            figures=figures,
            trace=tuple(trace),
            unit=_unit(unit),
            average_income_tax_rate=rate(AVERAGE_RATES[jurisdiction_code]),
            marginal_income_tax_rate=rate(MARGINAL_RATES[jurisdiction_code]),
        )
