"""Take-home pay for a gross salary. Implements TakeHomeCalculationsPort.

Checks the request against what is supported, asks the tax engine for the deductions and
subtracts them. `service-gen sync` never overwrites this file.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from app.application.ports.tax_engine import TaxEnginePort
from app.domain.errors import InvalidArgumentError
from app.domain.take_home import (
    CENTS,
    SALARY_LIMIT,
    SUPPORTED_JURISDICTIONS,
    TakeHomeResult,
)


class TakeHomeCalculationsService:
    def __init__(self, engine: TaxEnginePort) -> None:
        self._engine = engine

    async def compute_take_home_calculation(
        self,
        jurisdiction_code: str,
        year: int,
        salary: Decimal,
        language_code: str,
        include_trace: bool,
    ) -> TakeHomeResult:
        if language_code != "en":
            raise InvalidArgumentError(
                "language_code", f"language_code {language_code} is not supported; use en"
            )
        if salary <= 0:
            raise InvalidArgumentError("salary", "salary must be above 0")
        if salary >= SALARY_LIMIT:
            raise InvalidArgumentError("salary", "salary must be below 1,000,000,000,000,000")
        provisional = _provisional(jurisdiction_code, year)
        # The engine is plain synchronous code; keep it off the event loop.
        figures = await asyncio.to_thread(
            self._engine.compute, jurisdiction_code, year, salary, include_trace
        )
        total_deductions = figures.cpp + figures.cpp2 + figures.ei + figures.income_tax
        return TakeHomeResult(
            salary=salary.quantize(CENTS),
            total_deductions=total_deductions.quantize(CENTS),
            take_home=(salary - total_deductions).quantize(CENTS),
            provisional=provisional,
            trace=figures.trace if include_trace else None,
        )


def _provisional(jurisdiction_code: str, year: int) -> bool:
    """Whether the year's figures are provisional; rejects an unsupported jurisdiction or year."""
    for jurisdiction in SUPPORTED_JURISDICTIONS:
        if jurisdiction.code != jurisdiction_code:
            continue
        for supported in jurisdiction.years:
            if supported.year == year:
                return supported.provisional
        raise InvalidArgumentError(
            "year", f"year {year} is not supported for {jurisdiction_code} yet"
        )
    raise InvalidArgumentError(
        "jurisdiction_code", f"jurisdiction_code {jurisdiction_code} is not supported yet"
    )
