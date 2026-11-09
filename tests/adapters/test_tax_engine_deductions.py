"""The tax-engine adapter on its own: no HTTP; the real engine, or a fake one that fails."""

from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn

import pytest

from app.adapters.outbound.tax_engine import TaxEngineDeductions
from app.application.errors import DeductionsUnavailableError
from app.domain.take_home import SUPPORTED_JURISDICTIONS

ONTARIO_ITEMS = SUPPORTED_JURISDICTIONS[0].deduction_items  # CA-ON, the only jurisdiction


async def calculate(
    calculator: TaxEngineDeductions, year: int = 2025, language: str = "en", trace: bool = False
) -> Any:
    return await calculator.calculate("CA-ON", year, Decimal(70000), language, ONTARIO_ITEMS, trace)


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


class FailingEngine:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def compute(self, *args: object) -> NoReturn:
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
