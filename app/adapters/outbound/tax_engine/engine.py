"""Driven adapter: asks tax-engine for the deductions of a salary.

It only maps each deduction item the application asks for to the engine's form and kind, and reads
the figure off the worksheet: CPP (base and enhanced) and CPP2 from Schedule 8, EI from T2204
line 16 and income tax as T1 line 167 (federal and Ontario tax less credits and benefits). What
"total deductions" is made of is decided by the domain. The engine is synchronous, so it runs on
a worker thread here; the application only sees an async port. Everything the engine raises is
translated into the port's own errors.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Protocol

from tax_engine import build_tax_computation
from tax_engine.adapters.inbound.trace_english import EnglishTraceRenderer
from tax_engine.domain.artifact import Artifact
from tax_engine.domain.errors import DomainError as EngineError
from tax_engine.domain.jurisdiction_code import JurisdictionCode
from tax_engine.domain.worksheet import Worksheet
from tax_engine.jurisdictions.ca.catalog.income import EMPLOYMENT_INCOME
from tax_engine.registrations import artifact_kinds

from app.application.ports.deductions import DeductionsUnavailableError
from app.domain.take_home import DeductionFigure, Deductions, FormTrace, TraceEntry

ENGLISH = "en"

# Each deduction item to the engine's (form, kind) that holds its figure.
FIGURES = {
    "cpp_base": ("ca/schedule_8", "ca/schedule_8_cpp_base_contributions_on_return"),
    "cpp_enhanced": ("ca/schedule_8", "ca/cpp_part_3_line_12"),
    "cpp2": ("ca/schedule_8", "ca/cpp_part_3_line_22"),
    "ei": ("ca/t2204", "ca/t2204_line_16"),
    "income_tax": ("ca/t1_tax_and_credits", "ca/refund_or_balance_owing"),
}


class Engine(Protocol):
    """The part of tax-engine's computation service this adapter uses."""

    def compute(
        self, code: JurisdictionCode, tax_year: int, *inputs: Artifact[Decimal]
    ) -> Mapping[str, Sequence[Worksheet]]: ...


def _present(text: str | None) -> str | None:
    """The text, or None when there is none (the engine may give nothing or an empty string)."""
    return text or None


class TaxEngineDeductions:
    """Implements DeductionsCalculator with tax-engine; only English text is available."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = build_tax_computation() if engine is None else engine
        self._kinds = artifact_kinds()
        self._renderer = EnglishTraceRenderer()

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

        def figure(item: str) -> Decimal:
            form, kind = FIGURES[item]
            (sheet,) = sheets[form]
            value = sheet.get(self._kinds.kind(kind)).value
            if not isinstance(value, Decimal):
                raise TypeError(f"{kind} is not a decimal")
            return value

        trace: list[FormTrace] = []
        if with_trace:
            for form, form_sheets in sheets.items():
                for sheet in form_sheets:
                    lines = tuple(
                        TraceEntry(
                            label=line.label,
                            name=_present(line.label and sheet.title(line.label)),
                            reference=_present(line.label and sheet.reference(line.label)),
                            amount=line.amount,
                            text=self._renderer.render(line),
                        )
                        for line in sheet.trace
                    )
                    trace.append(FormTrace(form, _present(sheet.form_title), lines))
        return Deductions(
            figures=tuple(DeductionFigure(item, figure(item)) for item in items),
            trace=tuple(trace),
        )
