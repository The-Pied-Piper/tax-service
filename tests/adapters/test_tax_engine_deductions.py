"""The tax-engine adapter on its own: no HTTP; the real engine, or a fake one that fails."""

from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest
from tax_engine.registrations import artifact_kinds

from app.adapters.outbound.tax_engine import TaxEngineDeductions
from app.application.ports.deductions import DeductionsUnavailableError
from app.domain.take_home import SUPPORTED_JURISDICTIONS, Rate, Unit, find_jurisdiction

CAD = Unit("ca/cad", "before", "CA$", "CA$", False, False)
MONTHS = Unit("core/months", "after", "month", "months", True, False)
PERCENT = Unit("core/percent", "after", "%", "%", False, True)
ONTARIO_ITEMS = find_jurisdiction("CA-ON").deduction_items  # type: ignore[union-attr]


async def calculate(
    calculator: TaxEngineDeductions,
    year: int = 2025,
    language: str = "en",
    trace: bool = False,
    code: str = "CA-ON",
    salary: int = 70000,
) -> Any:
    return await calculator.calculate(code, year, Decimal(salary), language, ONTARIO_ITEMS, trace)


async def test_70000_in_ontario() -> None:
    deductions = await calculate(TaxEngineDeductions())
    assert {f.item: f.amount for f in deductions.figures} == {
        "cpp_base": Decimal("3291.75"),
        "cpp_enhanced": Decimal("665.00"),
        "cpp2": Decimal("0.00"),
        "ei": Decimal("1077.48"),
        "income_tax": Decimal("11497.09"),
    }
    assert deductions.trace == ()


@pytest.mark.parametrize(
    ("year", "average", "marginal"),
    [(2025, "0.1642", "0.2965"), (2026, "0.1591", "0.2965")],
)
async def test_the_average_and_marginal_rates_at_70000_with_their_unit(
    year: int, average: str, marginal: str
) -> None:
    deductions = await calculate(TaxEngineDeductions(), year=year)
    assert deductions.average_income_tax_rate == Rate(Decimal(average), PERCENT)
    assert deductions.marginal_income_tax_rate == Rate(Decimal(marginal), PERCENT)
    assert deductions.average_income_tax_rate.unit.as_percentage is True


async def test_the_money_unit_is_not_a_percentage() -> None:
    deductions = await calculate(TaxEngineDeductions())
    assert deductions.unit == CAD
    assert deductions.unit.as_percentage is False


async def test_trace_lines_are_text_with_a_figure() -> None:
    deductions = await calculate(TaxEngineDeductions(), trace=True)
    assert deductions.trace
    assert all(line.text for form in deductions.trace for line in form.lines)


async def test_a_language_it_cannot_write_is_the_ports_error() -> None:
    with pytest.raises(DeductionsUnavailableError):
        await calculate(TaxEngineDeductions(), language="fr")


async def test_an_item_it_does_not_know_is_the_ports_error() -> None:
    with pytest.raises(DeductionsUnavailableError):
        await TaxEngineDeductions().calculate(
            "CA-ON", 2025, Decimal(70000), "en", ("not_an_item",), False
        )


async def test_an_engine_failure_becomes_the_ports_error() -> None:
    with pytest.raises(DeductionsUnavailableError):
        await calculate(TaxEngineDeductions(), year=2024)


async def test_the_deductions_are_in_canadian_dollars() -> None:
    assert (await calculate(TaxEngineDeductions())).unit == CAD


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


class FailingEngine:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def compute(self, *args: object) -> NoReturn:
        raise self._error


class FakeSheet:
    """A worksheet the engine gives no titles or references for, with one line that has no label."""

    form_title = ""
    trace = (SimpleNamespace(label=None, amount=Decimal("1.00")),)

    def get(self, kind: Any) -> Any:
        return SimpleNamespace(value=Decimal("1.00"), unit=SimpleNamespace(identifier="ca/cad"))

    def unit(self, label: str) -> None:
        raise AssertionError("asked for the unit of a line with no label")

    def title(self, label: str) -> str:
        raise AssertionError("asked for the title of a line with no label")

    def reference(self, label: str) -> str:
        raise AssertionError("asked for the reference of a line with no label")


class FakeEngine:
    def compute(self, *args: Any) -> Any:
        return {"ca/t2204": [FakeSheet()], "ca-on/return": [FakeSheet()]}


async def test_what_the_engine_does_not_title_is_absent() -> None:
    calculator = TaxEngineDeductions(
        FakeEngine(), SimpleNamespace(render=lambda line, sheet: "one")
    )
    deductions = await calculator.calculate("CA-ON", 2025, Decimal(70000), "en", ("ei",), True)
    (form,) = (f for f in deductions.trace if f.form == "ca/t2204")
    assert form.name is None
    (line,) = form.lines
    assert (line.label, line.name, line.reference) == (None, None, None)


async def test_the_real_engine_titles_its_forms() -> None:
    deductions = await calculate(TaxEngineDeductions(), trace=True)
    names = {form.form: form.name for form in deductions.trace}
    assert (names["ca/schedule_8"] or "").startswith("Schedule 8")


async def test_sentences_name_figures_the_way_the_form_prints_them() -> None:
    deductions = await calculate(TaxEngineDeductions(), trace=True)
    (sheet,) = (form for form in deductions.trace if form.form == "ca/schedule_6")
    (line,) = (line for line in sheet.lines if line.label == "cwb_reduction_line_27")
    assert (
        line.text == "15% of line 25 (CA$42480.00) gives CA$6372.00 (rounded to the nearest cent)."
    )


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


async def test_every_supported_jurisdiction_year_and_language_works_with_the_real_engine() -> None:
    # The domain lists what is on offer; this keeps that list and the adapter in step.
    calculator = TaxEngineDeductions()
    for jurisdiction in SUPPORTED_JURISDICTIONS:
        for supported in jurisdiction.years:
            for language in jurisdiction.languages:
                deductions = await calculator.calculate(
                    jurisdiction.code,
                    supported.year,
                    Decimal(70000),
                    language,
                    jurisdiction.deduction_items,
                    False,
                )
                assert [f.item for f in deductions.figures] == list(jurisdiction.deduction_items)


AVERAGE_RATE = "ca-on/average_income_tax_rate"
MARGINAL_RATE = "ca-on/marginal_tax_rate"


class UnitSheet:
    """A worksheet whose figures each have the unit given for their kind (None for no unit)."""

    form_title = ""
    trace = ()

    def __init__(self, units: dict[str, str | None]) -> None:
        kinds = artifact_kinds()
        self._units = {kinds.kind(kind): unit for kind, unit in units.items()}
        for kind in (AVERAGE_RATE, MARGINAL_RATE):
            self._units.setdefault(kinds.kind(kind), "core/percent")

    def get(self, kind: Any) -> Any:
        unit = self._units[kind]
        identifier = None if unit is None else SimpleNamespace(identifier=unit)
        return SimpleNamespace(value=Decimal("1.00"), unit=identifier)


class UnitEngine:
    def __init__(self, units: dict[str, str | None]) -> None:
        self._units = units

    def compute(self, *args: Any) -> Any:
        sheet = UnitSheet(self._units)
        return {"ca/t2204": [sheet], "ca/schedule_8": [sheet], "ca-on/return": [sheet]}


EI = "ca/t2204_line_16"
CPP2 = "ca/cpp_part_3_line_22"


async def deductions_with_units(units: dict[str, str | None]) -> Any:
    calculator = TaxEngineDeductions(UnitEngine(units), SimpleNamespace(render=lambda *a: "one"))
    return await calculator.calculate("CA-ON", 2025, Decimal(70000), "en", ("ei", "cpp2"), False)


async def test_figures_that_share_a_unit_give_that_unit() -> None:
    assert (await deductions_with_units({EI: "ca/cad", CPP2: "ca/cad"})).unit == CAD


@pytest.mark.parametrize(
    "units",
    [
        {EI: "ca/cad", CPP2: "core/months"},
        {EI: "ca/cad", CPP2: None},
        {EI: None, CPP2: "ca/cad"},
        {EI: None, CPP2: None},
    ],
)
async def test_figures_that_do_not_share_one_unit_are_the_ports_error(
    units: dict[str, str | None],
) -> None:
    with pytest.raises(DeductionsUnavailableError):
        await deductions_with_units(units)


@pytest.mark.parametrize("rate", [AVERAGE_RATE, MARGINAL_RATE])
async def test_a_rate_without_a_unit_is_the_ports_error(rate: str) -> None:
    with pytest.raises(DeductionsUnavailableError):
        await deductions_with_units({EI: "ca/cad", CPP2: "ca/cad", rate: None})


# Alberta's income_tax is the deduction item for T1 line 167 (negative when a refund is due).
ALBERTA_INCOME_TAX = [
    (2025, 20000, "-1591.91"),
    (2025, 70000, "11183.76"),
    (2025, 200000, "57148.10"),
    (2026, 20000, "-1681.51"),
    (2026, 70000, "10812.98"),
    (2026, 200000, "56376.82"),
]
ALBERTA_RATES = [
    (2025, 20000, "0.0079", "0.145"),
    (2025, 70000, "0.1598", "0.305"),
    (2025, 200000, "0.2857", "0.42"),
    (2026, 20000, "0.0052", "0.14"),
    (2026, 70000, "0.1545", "0.305"),
    (2026, 200000, "0.2819", "0.42"),
]


@pytest.mark.parametrize(("year", "salary", "income_tax"), ALBERTA_INCOME_TAX)
async def test_alberta_income_tax_with_the_real_engine(
    year: int, salary: int, income_tax: str
) -> None:
    deductions = await calculate(TaxEngineDeductions(), year, code="CA-AB", salary=salary)
    figures = {f.item: f.amount for f in deductions.figures}
    assert figures["income_tax"] == Decimal(income_tax)
    assert deductions.unit == CAD


@pytest.mark.parametrize(("year", "salary", "average", "marginal"), ALBERTA_RATES)
async def test_alberta_rates_are_read_from_the_alberta_form(
    year: int, salary: int, average: str, marginal: str
) -> None:
    deductions = await calculate(
        TaxEngineDeductions(), year, trace=True, code="CA-AB", salary=salary
    )
    assert deductions.average_income_tax_rate == Rate(Decimal(average), PERCENT)
    assert deductions.marginal_income_tax_rate == Rate(Decimal(marginal), PERCENT)
    assert "ca-ab/return" in {form.form for form in deductions.trace}


@pytest.mark.parametrize("code", ["CA-BC", "XX", ""])
async def test_an_unknown_jurisdiction_is_the_ports_error(code: str) -> None:
    with pytest.raises(DeductionsUnavailableError):
        await TaxEngineDeductions().calculate(code, 2025, Decimal(70000), "en", ("ei",), False)


async def test_an_unknown_jurisdiction_is_the_ports_error_even_with_a_fake_engine() -> None:
    # Whatever the engine has, a code with no rate policy here is not served.
    calculator = TaxEngineDeductions(
        FakeEngine(), SimpleNamespace(render=lambda line, sheet: "one")
    )
    with pytest.raises(DeductionsUnavailableError):
        await calculator.calculate("CA-BC", 2025, Decimal(70000), "en", ("ei",), False)
