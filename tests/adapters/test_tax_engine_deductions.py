"""The tax-engine adapter on its own: no HTTP; the real engine, or a fake one that fails."""

from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn

import pytest
from tax_engine.application.models.take_home import FormTrace as EngineFormTrace
from tax_engine.application.models.take_home import Rate as EngineRate
from tax_engine.application.models.take_home import TakeHomeResult as EngineResult
from tax_engine.application.models.take_home import TraceEntry as EngineTraceEntry
from tax_engine.application.models.take_home import UnitDescription
from tax_engine.application.models.take_home_request import TakeHomeRequest

from app.adapters.outbound.tax_engine import TaxEngineDeductions
from app.application.ports.deductions import DeductionsUnavailableError
from app.domain.take_home import SUPPORTED_JURISDICTIONS, Rate, Unit

CAD = Unit("ca/cad", "before", "CA$", "CA$", False, False)
MONTHS = Unit("core/months", "after", "month", "months", True, False)
PERCENT = Unit("core/percent", "after", "%", "%", False, True)


async def calculate(
    calculator: TaxEngineDeductions,
    year: int = 2025,
    language: str = "en",
    trace: bool = False,
    code: str = "CA-ON",
    salary: int = 70000,
) -> Any:
    return await calculator.calculate(code, year, Decimal(salary), language, trace)


async def test_70000_in_ontario() -> None:
    deductions = await calculate(TaxEngineDeductions())
    assert deductions.total_deductions == Decimal("16531.32")
    assert deductions.income_tax == Decimal("11497.09")
    assert deductions.unit == CAD
    assert deductions.trace == ()


@pytest.mark.parametrize("year", [2025, 2026])
async def test_the_rates_come_with_their_unit_from_the_same_answer(year: int) -> None:
    deductions = await calculate(TaxEngineDeductions(), year=year)
    assert deductions.average_income_tax_rate.unit == PERCENT
    assert deductions.marginal_income_tax_rate.unit == PERCENT
    assert deductions.average_income_tax_rate.unit.as_percentage is True


# The average rate is the total taken off over the salary (income tax, CPP, CPP2 and EI): the
# figure it is printed to four decimals, so it is checked against the total, not a pinned number.
@pytest.mark.parametrize("code", [j.code for j in SUPPORTED_JURISDICTIONS])
@pytest.mark.parametrize("year", [2025, 2026])
@pytest.mark.parametrize("salary", [20000, 70000, 200000])
async def test_the_average_rate_is_the_total_deductions_over_the_salary(
    code: str, year: int, salary: int
) -> None:
    deductions = await calculate(TaxEngineDeductions(), year, code=code, salary=salary)
    exact = deductions.total_deductions / salary
    assert abs(deductions.average_income_tax_rate.amount - exact) <= Decimal("0.00005")


# The marginal rate is the change of the total per extra dollar: checked against the answer for
# $100 more salary, away from any band edge.
@pytest.mark.parametrize("code", [j.code for j in SUPPORTED_JURISDICTIONS])
@pytest.mark.parametrize("year", [2025, 2026])
@pytest.mark.parametrize("salary", [30000, 70000, 150000])
async def test_the_marginal_rate_is_the_change_of_the_total_per_extra_dollar(
    code: str, year: int, salary: int
) -> None:
    calculator = TaxEngineDeductions()
    low = await calculate(calculator, year, code=code, salary=salary)
    high = await calculate(calculator, year, code=code, salary=salary + 100)
    change = (high.total_deductions - low.total_deductions) / 100
    assert abs(low.marginal_income_tax_rate.amount - change) <= Decimal("0.005")


async def test_it_asks_the_engine_once_with_the_rates_and_the_trace_flags() -> None:
    engine = RecordingEngine()
    calculator = TaxEngineDeductions(engine)
    await calculator.calculate("CA-ON", 2025, Decimal("70000"), "en", True)
    await calculator.calculate("CA-ON", 2025, Decimal("70000"), "en", False)
    assert [(r.include_rates, r.include_trace) for r in engine.requests] == [
        (True, True),
        (True, False),
    ]
    assert all(str(r.jurisdiction) == "CA-ON" and r.tax_year == 2025 for r in engine.requests)


async def test_trace_lines_are_text_with_a_figure() -> None:
    deductions = await calculate(TaxEngineDeductions(), trace=True)
    assert deductions.trace
    assert all(line.text for form in deductions.trace for line in form.lines)


async def test_a_language_it_cannot_write_is_the_ports_error() -> None:
    with pytest.raises(DeductionsUnavailableError):
        await calculate(TaxEngineDeductions(), language="fr")


async def test_an_engine_failure_becomes_the_ports_error() -> None:
    with pytest.raises(DeductionsUnavailableError):
        await calculate(TaxEngineDeductions(), year=2024)


async def test_trace_lines_carry_the_unit_of_their_figure() -> None:
    deductions = await calculate(TaxEngineDeductions(), trace=True)
    (t2204,) = (form for form in deductions.trace if form.form == "ca/t2204")
    ei = [line for line in t2204.lines if line.amount == Decimal("1077.48")]
    assert ei
    assert all(line.unit == CAD for line in ei)
    lines = [line for form in deductions.trace for line in form.lines]
    assert MONTHS in [line.unit for line in lines]
    assert None in [line.unit for line in lines]
    assert PERCENT in [line.unit for line in lines]
    assert {line.unit for line in lines} <= {CAD, MONTHS, PERCENT, None}


async def test_the_real_engine_titles_its_forms() -> None:
    deductions = await calculate(TaxEngineDeductions(), trace=True)
    names = {form.form: form.name for form in deductions.trace}
    assert (names["ca/schedule_8"] or "").startswith("Schedule 8")


async def test_both_t1_parts_carry_the_one_t1_title() -> None:
    deductions = await calculate(TaxEngineDeductions(), trace=True)
    names = {form.form: form.name for form in deductions.trace}
    assert names["ca/t1_taxable_income"] == "T1 Income Tax and Benefit Return"
    assert names["ca/t1_tax_and_credits"] == "T1 Income Tax and Benefit Return"


async def test_sentences_name_figures_the_way_the_form_prints_them() -> None:
    deductions = await calculate(TaxEngineDeductions(), trace=True)
    (sheet,) = (form for form in deductions.trace if form.form == "ca/schedule_6")
    (line,) = (line for line in sheet.lines if line.label == "cwb_reduction_line_27")
    assert (
        line.text == "15% of line 25 (CA$42480.00) gives CA$6372.00 (rounded to the nearest cent)."
    )


async def test_every_supported_jurisdiction_year_and_language_works_with_the_real_engine() -> None:
    # The domain lists what is on offer; this keeps that list and the engine in step.
    calculator = TaxEngineDeductions()
    for jurisdiction in SUPPORTED_JURISDICTIONS:
        for supported in jurisdiction.years:
            for language in jurisdiction.languages:
                deductions = await calculator.calculate(
                    jurisdiction.code, supported.year, Decimal(70000), language, False
                )
                assert deductions.total_deductions > deductions.income_tax > 0
                assert deductions.average_income_tax_rate.amount > 0


CAD_UNIT = UnitDescription("ca/cad", "before", "CA$", "CA$", False, False)
PERCENT_UNIT = UnitDescription("core/percent", "after", "%", "%", False, True)


AVERAGE_RATE = EngineRate(Decimal("0.2362"), PERCENT_UNIT)
MARGINAL_RATE = EngineRate(Decimal("0.3433"), PERCENT_UNIT)


def engine_result(
    average: EngineRate | None = AVERAGE_RATE,
    marginal: EngineRate | None = MARGINAL_RATE,
    trace: tuple[EngineFormTrace, ...] | None = None,
) -> EngineResult:
    return EngineResult(
        salary=Decimal("70000.00"),
        figures=(),
        total_deductions=Decimal("16531.32"),
        income_tax=Decimal("11497.09"),
        take_home=Decimal("53468.68"),
        unit=CAD_UNIT,
        average_tax_rate=average,
        marginal_tax_rate=marginal,
        trace=trace,
    )


class RecordingEngine:
    def __init__(self, result: EngineResult | None = None) -> None:
        self.requests: list[TakeHomeRequest] = []
        self._result = engine_result() if result is None else result

    def compute(self, request: TakeHomeRequest) -> EngineResult:
        self.requests.append(request)
        return self._result


async def test_what_the_engine_does_not_title_is_absent() -> None:
    entry = EngineTraceEntry(None, "", "", Decimal("1.00"), "one", None)
    trace = (EngineFormTrace("ca/t2204", None, (entry,)),)
    calculator = TaxEngineDeductions(RecordingEngine(engine_result(trace=trace)))
    deductions = await calculator.calculate("CA-ON", 2025, Decimal(70000), "en", True)
    (form,) = deductions.trace
    assert form.name is None
    (line,) = form.lines
    assert (line.label, line.name, line.reference, line.unit) == (None, None, None, None)


@pytest.mark.parametrize(("average", "marginal"), [(None, "x"), ("x", None), (None, None)])
async def test_a_jurisdiction_without_rates_is_the_ports_error(
    average: str | None, marginal: str | None
) -> None:
    rate = EngineRate(Decimal("0.1"), PERCENT_UNIT)
    result = engine_result(
        average=None if average is None else rate, marginal=None if marginal is None else rate
    )
    calculator = TaxEngineDeductions(RecordingEngine(result))
    with pytest.raises(DeductionsUnavailableError):
        await calculator.calculate("CA-ON", 2025, Decimal(70000), "en", False)


async def test_the_rates_and_unit_are_mapped_from_the_engine_answer() -> None:
    calculator = TaxEngineDeductions(RecordingEngine())
    deductions = await calculator.calculate("CA-ON", 2025, Decimal(70000), "en", False)
    assert deductions.average_income_tax_rate == Rate(Decimal("0.2362"), PERCENT)
    assert deductions.marginal_income_tax_rate == Rate(Decimal("0.3433"), PERCENT)
    assert deductions.unit == CAD


class FailingEngine:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def compute(self, request: TakeHomeRequest) -> NoReturn:
        raise self._error


@pytest.mark.parametrize(
    "error",
    [
        InvalidOperation("too many digits"),
        TypeError("no rendering"),
        KeyError("form"),
        ValueError(),
    ],
)
async def test_other_engine_failures_become_the_ports_error(error: Exception) -> None:
    calculator = TaxEngineDeductions(FailingEngine(error))
    with pytest.raises(DeductionsUnavailableError):
        await calculate(calculator)
