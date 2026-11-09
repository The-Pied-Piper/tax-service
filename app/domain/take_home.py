"""Take-home pay: what a computation takes in and gives back, and the jurisdictions it covers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

CENTS = Decimal("0.01")
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
class Deductions:
    """What a salary costs in contributions and tax, with the steps that explain it."""

    total: Decimal
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

    def year(self, year: int) -> SupportedYear | None:
        return next((supported for supported in self.years if supported.year == year), None)


# Which jurisdictions and years the service offers, and which are provisional, is its own policy.
SUPPORTED_JURISDICTIONS = (
    SupportedJurisdiction(
        "CA-ON", (SupportedYear(2025, provisional=False), SupportedYear(2026, provisional=True))
    ),
)


def find_jurisdiction(code: str) -> SupportedJurisdiction | None:
    return next((j for j in SUPPORTED_JURISDICTIONS if j.code == code), None)
