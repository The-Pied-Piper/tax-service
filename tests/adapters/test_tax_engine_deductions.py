"""The tax-engine adapter on its own: real engine, no HTTP."""

from decimal import Decimal, InvalidOperation

import pytest

from app.adapters.outbound.tax_engine import TaxEngineDeductions
from app.application.ports.deductions import DeductionsUnavailableError
from app.domain.errors import InvalidArgumentError


async def test_70000_in_ontario() -> None:
    deductions = await TaxEngineDeductions().calculate("CA-ON", 2025, Decimal(70000), "en", False)
    assert deductions.total == Decimal("16531.32")
    assert deductions.trace == ()


async def test_trace_lines_are_text_with_a_figure() -> None:
    deductions = await TaxEngineDeductions().calculate("CA-ON", 2025, Decimal(70000), "en", True)
    assert deductions.trace
    assert all(line.text for form in deductions.trace for line in form.lines)


async def test_a_language_it_cannot_write_is_refused() -> None:
    with pytest.raises(InvalidArgumentError) as error:
        await TaxEngineDeductions().calculate("CA-ON", 2025, Decimal(70000), "fr", False)
    assert error.value.field == "language_code"


async def test_an_engine_failure_becomes_the_ports_error() -> None:
    with pytest.raises(DeductionsUnavailableError):
        await TaxEngineDeductions().calculate("CA-ON", 2024, Decimal(70000), "en", False)


async def test_an_arithmetic_failure_becomes_the_ports_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calculator = TaxEngineDeductions()

    def overflow(*args: object) -> None:
        raise InvalidOperation("too many digits")

    monkeypatch.setattr(calculator, "_calculate", overflow)
    with pytest.raises(DeductionsUnavailableError):
        await calculator.calculate("CA-ON", 2025, Decimal(70000), "en", False)
