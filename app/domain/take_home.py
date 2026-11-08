"""Take-home pay: what a computation takes in and gives back, and the jurisdictions it covers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

CENTS = Decimal("0.01")


@dataclass(frozen=True)
class TraceEntry:
    """One explained step. `label` names the figure the step is about, when the engine says."""

    label: str | None
    amount: Decimal
    text: str


@dataclass(frozen=True)
class FormTrace:
    form: str
    lines: tuple[TraceEntry, ...]


@dataclass(frozen=True)
class EngineFigures:
    """What the tax engine returns for one salary: each deduction, the year, and the trace."""

    cpp: Decimal
    cpp2: Decimal
    ei: Decimal
    income_tax: Decimal
    trace: tuple[FormTrace, ...]


@dataclass(frozen=True)
class TakeHomeResult:
    salary: Decimal
    total_deductions: Decimal
    take_home: Decimal
    provisional: bool
    trace: tuple[FormTrace, ...] | None


@dataclass(frozen=True)
class SupportedYear:
    year: int
    provisional: bool


@dataclass(frozen=True)
class SupportedJurisdiction:
    code: str
    years: tuple[SupportedYear, ...]


# Hardcoded for now; the list will come from the engine when it can say what it supports.
SUPPORTED_JURISDICTIONS = (
    SupportedJurisdiction(
        "CA-ON", (SupportedYear(2025, provisional=False), SupportedYear(2026, provisional=True))
    ),
)
