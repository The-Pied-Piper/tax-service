"""Take-home pay: what a computation takes in and gives back, and the jurisdictions it covers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.errors import InvalidArgumentError

CENTS = Decimal("0.01")
# The largest salary the service accepts (product limit); anything at or above it is refused.
SALARY_LIMIT = Decimal("1e15")


def check_salary(salary: Decimal) -> None:
    """Refuses a salary that is not a number, not above 0, finer than cents or at the limit."""
    if not salary.is_finite():
        raise InvalidArgumentError("salary", "salary must be a number")
    if salary <= 0:
        raise InvalidArgumentError("salary", "salary must be above 0")
    if salary >= SALARY_LIMIT:
        raise InvalidArgumentError("salary", f"salary must be below {SALARY_LIMIT:,.0f}")
    if salary != salary.quantize(CENTS):
        raise InvalidArgumentError("salary", "salary must have at most two decimal places")


@dataclass(frozen=True)
class Unit:
    """What a figure is counted in, as data for the caller to format. `name` is the calculator's
    identifier of the unit, opaque: compare it, do not parse it. `placement` is `before` or
    `after` the number; `singular` is the text beside exactly 1 and `plural` the text beside any
    other number; `spaced` says whether one space separates the text from the number.
    `as_percentage` says the figures are fractions written as percentages: 0.2965 is shown as
    "29.65%"."""

    name: str
    placement: str
    singular: str
    plural: str
    spaced: bool
    as_percentage: bool


@dataclass(frozen=True)
class TraceEntry:
    """One explained step. `label` names the figure it is about, when the calculator names one;
    `name` is that figure's display name in English, and `reference` what the form prints beside
    it, each when the calculator gives one. `unit` is the unit of `amount`, when it has one."""

    label: str | None
    name: str | None
    reference: str | None
    amount: Decimal | None
    text: str
    unit: Unit | None


@dataclass(frozen=True)
class FormTrace:
    """The steps of one form. `form` and each entry's `label` are the calculator's own
    identifiers, passed through unchanged and opaque to this service: they are not translated,
    so a calculator that renames one changes what callers see. `name` is the form's display
    name in English, when the calculator gives one."""

    form: str
    name: str | None
    lines: tuple[TraceEntry, ...]


@dataclass(frozen=True)
class Rate:
    """A rate of income tax and the unit it is in. `amount` is the figure as the calculator gives
    it (a fraction, not a percentage); `unit` says how to write it."""

    amount: Decimal
    unit: Unit


@dataclass(frozen=True)
class Deductions:
    """What the calculator took off the salary, with the steps that explain it.

    `total_deductions` is the plain sum of the figures it takes off (contributions and income tax)
    and `income_tax` is the tax part of it: the total payable, before the total credits are
    subtracted. The calculator decides what the total is made of, not this service. `unit` is the
    one unit the money figures are in. The two rates have their own units; they include the
    contributions and leave out credits paid at filing.
    """

    total_deductions: Decimal
    income_tax: Decimal
    trace: tuple[FormTrace, ...]
    unit: Unit
    average_income_tax_rate: Rate
    marginal_income_tax_rate: Rate


@dataclass(frozen=True)
class TakeHomeResult:
    salary: Decimal
    total_deductions: Decimal
    income_tax: Decimal
    take_home: Decimal
    provisional: bool
    unit: Unit
    average_income_tax_rate: Rate
    marginal_income_tax_rate: Rate
    trace: tuple[FormTrace, ...] | None

    @classmethod
    def of(
        cls,
        salary: Decimal,
        deductions: Deductions,
        provisional: bool,
        trace: tuple[FormTrace, ...] | None,
    ) -> TakeHomeResult:
        """Take-home pay is the salary minus the total deductions, in whole cents."""
        return cls(
            salary=salary.quantize(CENTS),
            total_deductions=deductions.total_deductions.quantize(CENTS),
            income_tax=deductions.income_tax.quantize(CENTS),
            take_home=(salary - deductions.total_deductions).quantize(CENTS),
            provisional=provisional,
            unit=deductions.unit,
            average_income_tax_rate=deductions.average_income_tax_rate,
            marginal_income_tax_rate=deductions.marginal_income_tax_rate,
            trace=trace,
        )


@dataclass(frozen=True)
class SupportedYear:
    year: int
    provisional: bool


@dataclass(frozen=True)
class SupportedJurisdiction:
    code: str
    # Display name in English.
    name: str
    years: tuple[SupportedYear, ...]
    # The languages the text can be written in; the first is used when none is asked for.
    languages: tuple[str, ...]

    @property
    def default_language(self) -> str:
        return self.languages[0]

    def year(self, year: int) -> SupportedYear | None:
        return next((supported for supported in self.years if supported.year == year), None)


# Which jurisdictions and years the service offers, and which are provisional, is its own policy.
SUPPORTED_JURISDICTIONS = (
    SupportedJurisdiction(
        "CA-ON",
        "Ontario",
        (SupportedYear(2025, provisional=False), SupportedYear(2026, provisional=True)),
        languages=("en",),
    ),
    SupportedJurisdiction(
        "CA-AB",
        "Alberta",
        (SupportedYear(2025, provisional=False), SupportedYear(2026, provisional=True)),
        languages=("en",),
    ),
    SupportedJurisdiction(
        "CA-BC",
        "British Columbia",
        (SupportedYear(2025, provisional=False), SupportedYear(2026, provisional=True)),
        languages=("en",),
    ),
    SupportedJurisdiction(
        "CA-MB",
        "Manitoba",
        (SupportedYear(2025, provisional=False), SupportedYear(2026, provisional=True)),
        languages=("en",),
    ),
    SupportedJurisdiction(
        "CA-SK",
        "Saskatchewan",
        (SupportedYear(2025, provisional=False), SupportedYear(2026, provisional=True)),
        languages=("en",),
    ),
    SupportedJurisdiction(
        "CA-NL",
        "Newfoundland and Labrador",
        (SupportedYear(2025, provisional=False), SupportedYear(2026, provisional=True)),
        languages=("en",),
    ),
)


def find_jurisdiction(code: str) -> SupportedJurisdiction | None:
    return next((j for j in SUPPORTED_JURISDICTIONS if j.code == code), None)
