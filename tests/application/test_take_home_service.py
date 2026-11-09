"""The take-home service against a fake deductions calculator: no HTTP, no engine."""

from decimal import Decimal

import pytest

from app.application.ports.deductions import DeductionsUnavailableError
from app.application.services.take_home_calculations_service import TakeHomeCalculationsService
from app.domain.errors import InvalidArgumentError
from app.domain.take_home import (
    DeductionFigure,
    Deductions,
    FormTrace,
    TakeHomeResult,
    TraceEntry,
    find_jurisdiction,
)

TRACE = (FormTrace("ex/form", (TraceEntry("ex_line", Decimal("1.00"), "one"),)),)
# What a $70,000 salary pays of each item in CA-ON 2025; they add up to 16531.32.
FIGURES = {
    "cpp_base": "3291.75",
    "cpp_enhanced": "665.00",
    "cpp2": "0.00",
    "ei": "1077.48",
    "income_tax": "11497.09",
}


class FakeDeductions:
    def __init__(self, figures: list[tuple[str, str]] | None = None) -> None:
        self.figures = list(FIGURES.items()) if figures is None else figures
        self.calls: list[tuple[str, int, Decimal, str, tuple[str, ...], bool]] = []

    async def calculate(
        self,
        jurisdiction_code: str,
        year: int,
        salary: Decimal,
        language_code: str,
        items: tuple[str, ...],
        with_trace: bool,
    ) -> Deductions:
        self.calls.append((jurisdiction_code, year, salary, language_code, items, with_trace))
        figures = tuple(DeductionFigure(item, Decimal(amount)) for item, amount in self.figures)
        return Deductions(figures, TRACE if with_trace else ())


async def compute(
    fake: FakeDeductions,
    salary: str = "70000",
    year: int = 2025,
    code: str = "CA-ON",
    trace: bool = False,
    language: str | None = "en",
) -> TakeHomeResult:
    service = TakeHomeCalculationsService(fake)
    return await service.compute_take_home_calculation(code, year, Decimal(salary), language, trace)


async def test_take_home_is_salary_minus_the_sum_of_the_items() -> None:
    result = await compute(FakeDeductions())
    assert (result.salary, result.total_deductions, result.take_home) == (
        Decimal("70000.00"),
        Decimal("16531.32"),
        Decimal("53468.68"),
    )


async def test_it_asks_for_the_items_the_jurisdiction_declares() -> None:
    fake = FakeDeductions()
    await compute(fake)
    jurisdiction = find_jurisdiction("CA-ON")
    assert jurisdiction is not None
    assert fake.calls[0][4] == jurisdiction.deduction_items


@pytest.mark.parametrize(
    "answer",
    [
        [("ei", "1077.48")],  # items missing
        [*FIGURES.items(), ("extra", "1.00")],  # an item nobody asked for
        [*FIGURES.items(), ("ei", "1077.48")],  # an item twice
        [(item, "1.00") for item in [*FIGURES][:-1]] + [("ei", "1.00")],  # one twice, one gone
    ],
)
async def test_a_calculator_that_answers_for_other_items_is_an_error(
    answer: list[tuple[str, str]],
) -> None:
    with pytest.raises(DeductionsUnavailableError):
        await compute(FakeDeductions(answer))


async def test_the_items_may_come_back_in_any_order() -> None:
    result = await compute(FakeDeductions(list(reversed(FIGURES.items()))))
    assert result.total_deductions == Decimal("16531.32")


async def test_provisional_follows_the_supported_year() -> None:
    assert (await compute(FakeDeductions(), year=2025)).provisional is False
    assert (await compute(FakeDeductions(), year=2026)).provisional is True


async def test_trace_only_when_asked() -> None:
    fake = FakeDeductions()
    assert (await compute(fake, trace=False)).trace is None
    assert (await compute(fake, trace=True)).trace == TRACE
    assert [call[5] for call in fake.calls] == [False, True]


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"code": "CA-AB"}, "jurisdiction_code"),
        ({"year": 2024}, "year"),
        ({"salary": "0"}, "salary"),
        ({"salary": "1000000000000000"}, "salary"),
    ],
)
async def test_refuses_what_is_not_supported_before_asking_for_deductions(
    kwargs: dict[str, object], field: str
) -> None:
    fake = FakeDeductions()
    with pytest.raises(InvalidArgumentError) as error:
        await compute(fake, **kwargs)  # type: ignore[arg-type]
    assert error.value.field == field
    assert fake.calls == []


async def test_a_negative_figure_is_summed_and_take_home_can_exceed_the_salary() -> None:
    # Refundable credits can exceed the tax, so the income tax item is negative (made-up split).
    fake = FakeDeductions(
        [
            ("cpp_base", "1000.00"),
            ("cpp_enhanced", "100.00"),
            ("cpp2", "0.00"),
            ("ei", "300.00"),
            ("income_tax", "-1565.16"),
        ]
    )
    result = await compute(fake, salary="20000")
    assert (result.total_deductions, result.take_home) == (Decimal("-165.16"), Decimal("20165.16"))


async def test_an_unsupported_language_is_refused_naming_the_field() -> None:
    with pytest.raises(InvalidArgumentError) as error:
        await compute(FakeDeductions(), language="fr")
    assert error.value.field == "language_code"


async def test_no_language_asked_means_the_jurisdictions_default() -> None:
    fake = FakeDeductions()
    await compute(fake, language=None)
    assert fake.calls[0][3] == "en"


async def test_the_salary_limit_message_states_the_limit() -> None:
    with pytest.raises(InvalidArgumentError, match="below 1,000,000,000,000,000"):
        await compute(FakeDeductions(), salary="1000000000000000")


@pytest.mark.parametrize("salary", ["NaN", "Infinity", "-Infinity", "70000.001", "1e30"])
async def test_a_salary_that_is_not_plain_cents_below_the_limit_is_refused(salary: str) -> None:
    with pytest.raises(InvalidArgumentError) as error:
        await compute(FakeDeductions(), salary=salary)
    assert error.value.field == "salary"
