"""Take-home pay: what a computation takes in and gives back, and the jurisdictions it covers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

CENTS = Decimal("0.01")
DEFAULT_LANGUAGE_CODE = "en"
# The largest salary the service accepts (product limit); anything at or above it is refused.
SALARY_LIMIT = Decimal("1e15")


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
class DeductionFigure:
    """One kind of deduction (for example `ei`) and what the salary pays of it."""

    item: str
    amount: Decimal


@dataclass(frozen=True)
class Deductions:
    """The figures asked for, with the steps that explain them."""

    figures: tuple[DeductionFigure, ...]
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
    # What "total deductions" means here: the sum of exactly these items.
    deduction_items: tuple[str, ...]

    def year(self, year: int) -> SupportedYear | None:
        return next((supported for supported in self.years if supported.year == year), None)


# Which jurisdictions and years the service offers, and which are provisional, is its own policy.
SUPPORTED_JURISDICTIONS = (
    SupportedJurisdiction(
        "CA-ON",
        (SupportedYear(2025, provisional=False), SupportedYear(2026, provisional=True)),
        deduction_items=("cpp_base", "cpp_enhanced", "cpp2", "ei", "income_tax"),
    ),
)


def find_jurisdiction(code: str) -> SupportedJurisdiction | None:
    return next((j for j in SUPPORTED_JURISDICTIONS if j.code == code), None)
