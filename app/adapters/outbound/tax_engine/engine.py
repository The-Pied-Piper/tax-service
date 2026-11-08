"""Runs tax-engine for a salary and reads the take-home figures off its worksheets.

The figures are read by form and kind from the engine's own worksheets, as in tax-engine's
take-home notes: CPP (base and enhanced) from Schedule 8, CPP2 from Schedule 8 line 22, EI from
T2204 line 16 and income tax as T1 line 167 (federal and Ontario tax less credits and benefits).
"""

from __future__ import annotations

from decimal import Decimal

from tax_engine import build_tax_computation
from tax_engine.adapters.inbound.trace_english import EnglishTraceRenderer
from tax_engine.domain.artifact import Artifact
from tax_engine.domain.jurisdiction_code import JurisdictionCode
from tax_engine.jurisdictions.ca.catalog.income import EMPLOYMENT_INCOME
from tax_engine.registrations import artifact_kinds

from app.domain.take_home import EngineFigures, FormTrace, TraceEntry


class TaxEngineAdapter:
    def __init__(self) -> None:
        self._engine = build_tax_computation()
        self._kinds = artifact_kinds()
        self._renderer = EnglishTraceRenderer()

    def compute(
        self, jurisdiction_code: str, year: int, salary: Decimal, with_trace: bool
    ) -> EngineFigures:
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
                            label=_label(line),
                            amount=line.amount,
                            text=self._renderer.render(line),
                        )
                        for line in sheet.trace
                    )
                    trace.append(FormTrace(form=form, lines=lines))
        return EngineFigures(
            cpp=figure("ca/schedule_8", "ca/schedule_8_cpp_base_contributions_on_return")
            + figure("ca/schedule_8", "ca/cpp_part_3_line_12"),
            cpp2=figure("ca/schedule_8", "ca/cpp_part_3_line_22"),
            ei=figure("ca/t2204", "ca/t2204_line_16"),
            income_tax=figure("ca/t1_tax_and_credits", "ca/refund_or_balance_owing"),
            trace=tuple(trace),
        )


def _label(line: object) -> str | None:
    """The figure a trace line is about. tax-engine #591 gives each line a `label`; until it
    lands there is none, and this is the one place to read it from."""
    return None
