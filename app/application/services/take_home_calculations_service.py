"""Take-home pay for a gross salary. Implements TakeHomeCalculationsPort.

Checks the request against what is supported, asks for the deductions and subtracts them.
`service-gen sync` never overwrites this file.
"""

from __future__ import annotations

from decimal import Decimal

from app.application.ports.deductions import DeductionsCalculator, DeductionsUnavailableError
from app.domain.errors import InvalidArgumentError
from app.domain.take_home import (
    CENTS,
    SALARY_LIMIT,
    SupportedJurisdiction,
    SupportedYear,
    TakeHomeResult,
    find_jurisdiction,
)


class TakeHomeCalculationsService:
    def __init__(self, deductions: DeductionsCalculator) -> None:
        self._deductions = deductions

    async def compute_take_home_calculation(
        self,
        jurisdiction_code: str,
        year: int,
        salary: Decimal,
        language_code: str,
        include_trace: bool,
    ) -> TakeHomeResult:
        if salary <= 0:
            raise InvalidArgumentError("salary", "salary must be above 0")
        if salary >= SALARY_LIMIT:
            raise InvalidArgumentError("salary", "salary must be below 1,000,000,000,000,000")
        jurisdiction, supported_year = _supported(jurisdiction_code, year)
        deductions = await self._deductions.calculate(
            jurisdiction_code,
            year,
            salary,
            language_code,
            jurisdiction.deduction_items,
            include_trace,
        )
        if sorted(f.item for f in deductions.figures) != sorted(jurisdiction.deduction_items):
            raise DeductionsUnavailableError(f"{jurisdiction_code} {year}: wrong deduction items")
        total = sum((f.amount for f in deductions.figures), Decimal(0))
        return TakeHomeResult(
            salary=salary.quantize(CENTS),
            total_deductions=total.quantize(CENTS),
            take_home=(salary - total).quantize(CENTS),
            provisional=supported_year.provisional,
            trace=deductions.trace if include_trace else None,
        )


def _supported(jurisdiction_code: str, year: int) -> tuple[SupportedJurisdiction, SupportedYear]:
    """The supported jurisdiction and year; rejects an unsupported jurisdiction or year."""
    jurisdiction = find_jurisdiction(jurisdiction_code)
    if jurisdiction is None:
        raise InvalidArgumentError(
            "jurisdiction_code", f"jurisdiction_code {jurisdiction_code} is not supported yet"
        )
    supported = jurisdiction.year(year)
    if supported is None:
        raise InvalidArgumentError(
            "year", f"year {year} is not supported for {jurisdiction_code} yet"
        )
    return jurisdiction, supported
