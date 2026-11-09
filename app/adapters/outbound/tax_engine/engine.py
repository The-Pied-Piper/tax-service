"""Driven adapter: asks tax-engine for the deductions of a salary.

The figures are read by form and kind from the engine's own worksheets: CPP (base and enhanced)
from Schedule 8, CPP2 from Schedule 8 line 22, EI from T2204 line 16 and income tax as T1 line 167
(federal and Ontario tax less credits and benefits). The engine is synchronous, so it runs on a
worker thread here; the application only sees an async port. Everything the engine raises is
translated into the port's own errors.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from tax_engine import build_tax_computation
from tax_engine.adapters.inbound.trace_english import EnglishTraceRenderer
from tax_engine.domain.artifact import Artifact
from tax_engine.domain.errors import DomainError as EngineError
from tax_engine.domain.jurisdiction_code import JurisdictionCode
from tax_engine.jurisdictions.ca.catalog.income import EMPLOYMENT_INCOME
from tax_engine.registrations import artifact_kinds

from app.application.ports.deductions import DeductionsUnavailableError
from app.domain.errors import InvalidArgumentError
from app.domain.take_home import Deductions, FormTrace, TraceEntry

ENGLISH = "en"


class TaxEngineDeductions:
    """Implements DeductionsCalculator with tax-engine; only English text is available."""

    def __init__(self) -> None:
        self._engine = build_tax_computation()
        self._kinds = artifact_kinds()
        self._renderer = EnglishTraceRenderer()

    async def calculate(
        self,
        jurisdiction_code: str,
        year: int,
        salary: Decimal,
        language_code: str,
        with_trace: bool,
    ) -> Deductions:
        if language_code != ENGLISH:
            raise InvalidArgumentError(
                "language_code", f"language_code {language_code} is not supported; use {ENGLISH}"
            )
        try:
            return await asyncio.to_thread(
                self._calculate, jurisdiction_code, year, salary, with_trace
            )
        except (EngineError, KeyError, ValueError) as exc:
            raise DeductionsUnavailableError(
                f"{jurisdiction_code} {year}: {type(exc).__name__}"
            ) from exc

    def _calculate(
        self, jurisdiction_code: str, year: int, salary: Decimal, with_trace: bool
    ) -> Deductions:
        sheets = self._engine.compute(
            JurisdictionCode(jurisdiction_code), year, Artifact(EMPLOYMENT_INCOME, salary)
        )

        def figure(form: str, kind: str) -> Decimal:
            (sheet,) = sheets[form]
            value: Decimal = sheet.get(self._kinds.kind(kind)).value
            return value

        trace: list[FormTrace] = []
        if with_trace:
            for form, form_sheets in sheets.items():
                for sheet in form_sheets:
                    lines = tuple(
                        TraceEntry(
                            label=line.label,
                            amount=line.amount,
                            text=self._renderer.render(line),
                        )
                        for line in sheet.trace
                    )
                    trace.append(FormTrace(form=form, lines=lines))
        total = (
            figure("ca/schedule_8", "ca/schedule_8_cpp_base_contributions_on_return")
            + figure("ca/schedule_8", "ca/cpp_part_3_line_12")
            + figure("ca/schedule_8", "ca/cpp_part_3_line_22")
            + figure("ca/t2204", "ca/t2204_line_16")
            + figure("ca/t1_tax_and_credits", "ca/refund_or_balance_owing")
        )
        return Deductions(total=total, trace=tuple(trace))
