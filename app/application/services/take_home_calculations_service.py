"""Take-home pay for a gross salary. Implements TakeHomeCalculationsPort.

Checks the request against what is supported, asks for the deductions and subtracts them.
`service-gen sync` never overwrites this file.
"""

from __future__ import annotations

from decimal import Decimal

from app.application.ports.deductions import DeductionsCalculator, DeductionsUnavailableError
from app.domain.errors import InvalidArgumentError
from app.domain.take_home import (
    SupportedJurisdiction,
    SupportedYear,
    TakeHomeResult,
    check_salary,
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
        language_code: str | None,
        include_trace: bool,
    ) -> TakeHomeResult:
        check_salary(salary)
        jurisdiction, supported_year = _supported(jurisdiction_code, year)
        language = _language(jurisdiction, language_code)
        deductions = await self._deductions.calculate(
            jurisdiction_code,
            year,
            salary,
            language,
            jurisdiction.deduction_items,
            include_trace,
        )
        if sorted(f.item for f in deductions.figures) != sorted(jurisdiction.deduction_items):
            raise DeductionsUnavailableError(f"{jurisdiction_code} {year}: wrong deduction items")
        return TakeHomeResult.of(
            salary,
            deductions.figures,
            supported_year.provisional,
            deductions.trace if include_trace else None,
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


def _language(jurisdiction: SupportedJurisdiction, language_code: str | None) -> str:
    """The language asked for, or the default; rejects one the text cannot be written in."""
    if language_code is None:
        return jurisdiction.default_language
    if language_code not in jurisdiction.languages:
        raise InvalidArgumentError(
            "language_code",
            f"language_code {language_code} is not supported; use "
            + " or ".join(jurisdiction.languages),
        )
    return language_code
