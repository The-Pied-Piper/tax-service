"""The take-home service against a fake deductions calculator: no HTTP, no engine."""

from decimal import Decimal

import pytest

from app.application.services.take_home_calculations_service import TakeHomeCalculationsService
from app.domain.errors import InvalidArgumentError
from app.domain.take_home import Deductions, FormTrace, TakeHomeResult, TraceEntry

TRACE = (FormTrace("ex/form", (TraceEntry("ex_line", Decimal("1.00"), "one"),)),)


class FakeDeductions:
    def __init__(self, total: str = "16531.32") -> None:
        self.total = Decimal(total)
        self.calls: list[tuple[str, int, Decimal, str, bool]] = []

    async def calculate(
        self,
        jurisdiction_code: str,
        year: int,
        salary: Decimal,
        language_code: str,
        with_trace: bool,
    ) -> Deductions:
        self.calls.append((jurisdiction_code, year, salary, language_code, with_trace))
        return Deductions(self.total, TRACE if with_trace else ())


async def compute(
    fake: FakeDeductions, salary: str = "70000", year: int = 2025, code: str = "CA-ON"
) -> TakeHomeResult:
    service = TakeHomeCalculationsService(fake)
    return await service.compute_take_home_calculation(code, year, Decimal(salary), "en", False)


async def test_take_home_is_salary_minus_deductions() -> None:
    result = await compute(FakeDeductions())
    assert (result.salary, result.total_deductions, result.take_home) == (
        Decimal("70000.00"),
        Decimal("16531.32"),
        Decimal("53468.68"),
    )


async def test_provisional_follows_the_supported_year() -> None:
    assert (await compute(FakeDeductions(), year=2025)).provisional is False
    assert (await compute(FakeDeductions(), year=2026)).provisional is True


async def test_trace_only_when_asked() -> None:
    fake = FakeDeductions()
    service = TakeHomeCalculationsService(fake)
    without = await service.compute_take_home_calculation(
        "CA-ON", 2025, Decimal(70000), "en", False
    )
    with_trace = await service.compute_take_home_calculation(
        "CA-ON", 2025, Decimal(70000), "en", True
    )
    assert without.trace is None
    assert with_trace.trace == TRACE
    assert [call[4] for call in fake.calls] == [False, True]


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
