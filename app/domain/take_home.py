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
    amount: Decimal
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
class DeductionFigure:
    """One kind of deduction (for example `ei`) and what the salary pays of it.

    An amount can be negative: `income_tax` is the balance owing after refundable credits and
    benefits, so at a low salary the credits can exceed the tax. Take-home pay is then more than
    the salary; the total deductions are the plain sum of the figures.
    """

    item: str
    amount: Decimal


@dataclass(frozen=True)
class Rate:
    """A rate of income tax and the unit it is in. `amount` is the figure as the calculator gives
    it (a fraction, not a percentage); `unit` says how to write it."""

    amount: Decimal
    unit: Unit


@dataclass(frozen=True)
class Deductions:
    """The figures asked for, with the steps that explain them. `unit` is the one unit all the
    figures are in. The two rates have their own units and are not part of the figures."""

    figures: tuple[DeductionFigure, ...]
    trace: tuple[FormTrace, ...]
    unit: Unit
    average_income_tax_rate: Rate
    marginal_income_tax_rate: Rate


@dataclass(frozen=True)
class TakeHomeResult:
    salary: Decimal
    total_deductions: Decimal
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
        figures: tuple[DeductionFigure, ...],
        provisional: bool,
        unit: Unit,
        average_income_tax_rate: Rate,
        marginal_income_tax_rate: Rate,
        trace: tuple[FormTrace, ...] | None,
    ) -> TakeHomeResult:
        """Take-home pay is the salary minus the sum of the figures, in whole cents."""
        total = sum((figure.amount for figure in figures), Decimal(0))
        return cls(
            salary=salary.quantize(CENTS),
            total_deductions=total.quantize(CENTS),
            take_home=(salary - total).quantize(CENTS),
            provisional=provisional,
            unit=unit,
            average_income_tax_rate=average_income_tax_rate,
            marginal_income_tax_rate=marginal_income_tax_rate,
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
    # What "total deductions" means here: the sum of exactly these items.
    deduction_items: tuple[str, ...]
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
        deduction_items=("cpp_base", "cpp_enhanced", "cpp2", "ei", "income_tax"),
        languages=("en",),
    ),
    SupportedJurisdiction(
        "CA-AB",
        "Alberta",
        (SupportedYear(2025, provisional=False), SupportedYear(2026, provisional=True)),
        deduction_items=("cpp_base", "cpp_enhanced", "cpp2", "ei", "income_tax"),
        languages=("en",),
    ),
)


def find_jurisdiction(code: str) -> SupportedJurisdiction | None:
    return next((j for j in SUPPORTED_JURISDICTIONS if j.code == code), None)
