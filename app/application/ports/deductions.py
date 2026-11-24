"""Driven port: what a salary costs in contributions and tax in one jurisdiction and year."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from app.domain.take_home import Deductions


class DeductionsUnavailableError(Exception):
    """The deductions could not be calculated."""


class DeductionsCalculator(Protocol):
    async def calculate(
        self,
        jurisdiction_code: str,
        year: int,
        salary: Decimal,
        language_code: str,
        with_trace: bool,
    ) -> Deductions:
        """What `salary` pays in contributions and income tax, with the explaining trace (empty
        unless `with_trace`) and the average and marginal rates, from one calculation.

        Raises DeductionsUnavailableError when the language is unknown to it or the calculation
        itself fails.
        """
