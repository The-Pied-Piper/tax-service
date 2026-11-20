"""The tax-engine adapter on its own: no HTTP; the real engine, or a fake one that fails."""

from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest
from tax_engine.registrations import artifact_kinds

from app.adapters.outbound.tax_engine import TaxEngineDeductions
from app.adapters.outbound.tax_engine.engine import AVERAGE_RATES, MARGINAL_RATES
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


EI = "ca/t2204_premiums_deducted"
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


# British Columbia's income_tax is the deduction item for T1 line 167 (negative for a refund).
BRITISH_COLUMBIA_INCOME_TAX = [
    (2025, 20000, "-1474.91"),
    (2025, 70000, "10748.03"),
    (2025, 275000, "94556.99"),
    (2026, 20000, "-1561.51"),
    (2026, 70000, "10572.03"),
    (2026, 275000, "93405.74"),
]
BRITISH_COLUMBIA_RATES = [
    (2025, 20000, "0.0079", "0.145"),
    (2025, 70000, "0.1535", "0.282"),
    (2025, 275000, "0.3438", "0.535"),
    (2026, 20000, "0.0052", "0.14"),
    (2026, 70000, "0.1510", "0.282"),
    (2026, 275000, "0.3397", "0.535"),
]


@pytest.mark.parametrize(("year", "salary", "income_tax"), BRITISH_COLUMBIA_INCOME_TAX)
async def test_british_columbia_income_tax_with_the_real_engine(
    year: int, salary: int, income_tax: str
) -> None:
    deductions = await calculate(TaxEngineDeductions(), year, code="CA-BC", salary=salary)
    figures = {f.item: f.amount for f in deductions.figures}
    assert figures["income_tax"] == Decimal(income_tax)
    assert deductions.unit == CAD


@pytest.mark.parametrize(("year", "salary", "average", "marginal"), BRITISH_COLUMBIA_RATES)
async def test_british_columbia_rates_are_read_from_the_british_columbia_form(
    year: int, salary: int, average: str, marginal: str
) -> None:
    deductions = await calculate(
        TaxEngineDeductions(), year, trace=True, code="CA-BC", salary=salary
    )
    assert deductions.average_income_tax_rate == Rate(Decimal(average), PERCENT)
    assert deductions.marginal_income_tax_rate == Rate(Decimal(marginal), PERCENT)
    assert "ca-bc/return" in {form.form for form in deductions.trace}


# Manitoba's income_tax is the deduction item for T1 line 167 (negative for a refund).
MANITOBA_INCOME_TAX = [
    (2025, 20000, "-1190.83"),
    (2025, 70000, "13333.23"),
    (2025, 275000, "102748.13"),
    (2026, 20000, "-1277.21"),
    (2026, 70000, "13020.86"),
    (2026, 275000, "101929.24"),
]
MANITOBA_RATES = [
    (2025, 20000, "0.0221", "0.253"),
    (2025, 70000, "0.1905", "0.3325"),
    (2025, 275000, "0.3736", "0.5125212"),
    (2026, 20000, "0.0194", "0.248"),
    (2026, 70000, "0.1860", "0.3325"),
    (2026, 275000, "0.3707", "0.5125212"),
]


@pytest.mark.parametrize(("year", "salary", "income_tax"), MANITOBA_INCOME_TAX)
async def test_manitoba_income_tax_with_the_real_engine(
    year: int, salary: int, income_tax: str
) -> None:
    deductions = await calculate(TaxEngineDeductions(), year, code="CA-MB", salary=salary)
    figures = {f.item: f.amount for f in deductions.figures}
    assert figures["income_tax"] == Decimal(income_tax)
    assert deductions.unit == CAD


@pytest.mark.parametrize(("year", "salary", "average", "marginal"), MANITOBA_RATES)
async def test_manitoba_rates_are_read_from_the_manitoba_form(
    year: int, salary: int, average: str, marginal: str
) -> None:
    deductions = await calculate(
        TaxEngineDeductions(), year, trace=True, code="CA-MB", salary=salary
    )
    assert deductions.average_income_tax_rate == Rate(Decimal(average), PERCENT)
    assert deductions.marginal_income_tax_rate == Rate(Decimal(marginal), PERCENT)
    assert "ca-mb/return" in {form.form for form in deductions.trace}


# Saskatchewan's income_tax is the deduction item for T1 line 167 (negative for a refund).
SASKATCHEWAN_INCOME_TAX = [
    (2025, 20000, "-1474.91"),
    (2025, 70000, "12677.94"),
    (2025, 275000, "95287.57"),
    (2026, 20000, "-1561.51"),
    (2026, 70000, "12250.87"),
    (2026, 275000, "94295.37"),
]
SASKATCHEWAN_RATES = [
    (2025, 20000, "0.0079", "0.145"),
    (2025, 70000, "0.1811", "0.33"),
    (2025, 275000, "0.3465", "0.475"),
    (2026, 20000, "0.0052", "0.14"),
    (2026, 70000, "0.1750", "0.33"),
    (2026, 275000, "0.3429", "0.475"),
]


@pytest.mark.parametrize(("year", "salary", "income_tax"), SASKATCHEWAN_INCOME_TAX)
async def test_saskatchewan_income_tax_with_the_real_engine(
    year: int, salary: int, income_tax: str
) -> None:
    deductions = await calculate(TaxEngineDeductions(), year, code="CA-SK", salary=salary)
    figures = {f.item: f.amount for f in deductions.figures}
    assert figures["income_tax"] == Decimal(income_tax)
    assert deductions.unit == CAD


@pytest.mark.parametrize(("year", "salary", "average", "marginal"), SASKATCHEWAN_RATES)
async def test_saskatchewan_rates_are_read_from_the_saskatchewan_form(
    year: int, salary: int, average: str, marginal: str
) -> None:
    deductions = await calculate(
        TaxEngineDeductions(), year, trace=True, code="CA-SK", salary=salary
    )
    assert deductions.average_income_tax_rate == Rate(Decimal(average), PERCENT)
    assert deductions.marginal_income_tax_rate == Rate(Decimal(marginal), PERCENT)
    assert "ca-sk/return" in {form.form for form in deductions.trace}


# Newfoundland and Labrador's income_tax is T1 line 167 (negative for a refund).
NEWFOUNDLAND_INCOME_TAX = [
    (2025, 20000, "-1474.91"),
    (2025, 70000, "13733.13"),
    (2025, 275000, "103807.30"),
    (2026, 20000, "-1561.51"),
    (2026, 70000, "13217.18"),
    (2026, 275000, "102691.47"),
]
NEWFOUNDLAND_RATES = [
    (2025, 20000, "0.0079", "0.232"),
    (2025, 70000, "0.1962", "0.35"),
    (2025, 275000, "0.3775", "0.528"),
    (2026, 20000, "0.0052", "0.227"),
    (2026, 70000, "0.1888", "0.35"),
    (2026, 275000, "0.3734", "0.528"),
]


@pytest.mark.parametrize(("year", "salary", "income_tax"), NEWFOUNDLAND_INCOME_TAX)
async def test_newfoundland_income_tax_with_the_real_engine(
    year: int, salary: int, income_tax: str
) -> None:
    deductions = await calculate(TaxEngineDeductions(), year, code="CA-NL", salary=salary)
    figures = {f.item: f.amount for f in deductions.figures}
    assert figures["income_tax"] == Decimal(income_tax)
    assert deductions.unit == CAD


@pytest.mark.parametrize(("year", "salary", "average", "marginal"), NEWFOUNDLAND_RATES)
async def test_newfoundland_rates_are_read_from_the_newfoundland_form(
    year: int, salary: int, average: str, marginal: str
) -> None:
    deductions = await calculate(
        TaxEngineDeductions(), year, trace=True, code="CA-NL", salary=salary
    )
    assert deductions.average_income_tax_rate == Rate(Decimal(average), PERCENT)
    assert deductions.marginal_income_tax_rate == Rate(Decimal(marginal), PERCENT)
    assert "ca-nl/return" in {form.form for form in deductions.trace}


@pytest.mark.parametrize("code", [j.code for j in SUPPORTED_JURISDICTIONS])
def test_every_supported_jurisdiction_has_both_rate_forms(code: str) -> None:
    assert code in AVERAGE_RATES
    assert code in MARGINAL_RATES


@pytest.mark.parametrize("code", ["CA-QC", "XX", ""])
async def test_an_unknown_jurisdiction_is_the_ports_error(code: str) -> None:
    with pytest.raises(DeductionsUnavailableError):
        await TaxEngineDeductions().calculate(code, 2025, Decimal(70000), "en", ("ei",), False)


async def test_an_unknown_jurisdiction_is_the_ports_error_even_with_a_fake_engine() -> None:
    # Whatever the engine has, a code with no rate policy here is not served.
    calculator = TaxEngineDeductions(
        FakeEngine(), SimpleNamespace(render=lambda line, sheet: "one")
    )
    with pytest.raises(DeductionsUnavailableError):
        await calculator.calculate("CA-QC", 2025, Decimal(70000), "en", ("ei",), False)


@pytest.mark.parametrize("code", ["CA-ON", "CA-AB", "CA-SK", "CA-NL"])
@pytest.mark.parametrize(
    ("salary", "take_home"),
    [
        (1999, "1999.00"),
        (2000, "2000.00"),
        (2010, "2000.00"),
        (2033, "1999.66"),
        (2034, "2000.64"),
        (70000, None),
    ],
)
async def test_take_home_near_the_t2204_refund_threshold_with_the_real_engine(
    code: str, salary: int, take_home: str | None
) -> None:
    deductions = await calculate(TaxEngineDeductions(), code=code, salary=salary)
    figures = {f.item: f.amount for f in deductions.figures}
    expected = (
        take_home
        or {"CA-ON": "53468.68", "CA-AB": "53782.01", "CA-SK": "52287.83", "CA-NL": "51232.64"}[
            code
        ]
    )
    assert Decimal(salary) - sum(figures.values()) == Decimal(expected)


@pytest.mark.parametrize(
    ("salary", "take_home"),
    [
        (1999, "2074.00"),
        (2000, "2075.00"),
        (2010, "2075.00"),
        (2033, "2074.66"),
        (2034, "2075.64"),
    ],
)
async def test_british_columbia_take_home_near_the_t2204_refund_threshold(
    salary: int, take_home: str
) -> None:
    # The same as Ontario's and Alberta's plus the $75.00 BC sales tax credit (BC479), refundable.
    deductions = await calculate(TaxEngineDeductions(), code="CA-BC", salary=salary)
    figures = {f.item: f.amount for f in deductions.figures}
    assert Decimal(salary) - sum(figures.values()) == Decimal(take_home)


@pytest.mark.parametrize(
    ("salary", "take_home"),
    [
        (1999, "2174.01"),
        (2000, "2175.00"),
        (2010, "2174.90"),
        (2033, "2174.33"),
        (2034, "2175.30"),
    ],
)
async def test_manitoba_take_home_near_the_t2204_refund_threshold(
    salary: int, take_home: str
) -> None:
    # The same as Ontario's and Alberta's plus the Manitoba personal tax credit (MB479),
    # refundable: $195.00 less 1% of net income.
    deductions = await calculate(TaxEngineDeductions(), code="CA-MB", salary=salary)
    figures = {f.item: f.amount for f in deductions.figures}
    assert Decimal(salary) - sum(figures.values()) == Decimal(take_home)


@pytest.mark.parametrize("code", ["CA-ON", "CA-AB", "CA-BC", "CA-MB", "CA-SK", "CA-NL"])
@pytest.mark.parametrize(("salary", "ei"), [(2000, "32.80"), (2033, "33.34")])
async def test_ei_is_the_premium_withheld_with_the_real_engine(
    code: str, salary: int, ei: str
) -> None:
    deductions = await calculate(TaxEngineDeductions(), code=code, salary=salary)
    assert {f.item: f.amount for f in deductions.figures}["ei"] == Decimal(ei)
