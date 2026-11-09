"""Driven port: what a salary costs in contributions and tax in one jurisdiction and year."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from app.domain.take_home import Deductions


class DeductionsUnavailableError(Exception):
    """The deductions could not be calculated. `main.py` maps this to HTTP 500."""


class DeductionsCalculator(Protocol):
    async def calculate(
        self,
        jurisdiction_code: str,
        year: int,
        salary: Decimal,
        language_code: str,
        with_trace: bool,
    ) -> Deductions:
        """Total deductions for `salary`, with the explaining trace (empty unless `with_trace`).

        Raises InvalidArgumentError for a value the calculator cannot take, such as a language
        it cannot write, and DeductionsUnavailableError when the calculation itself fails.
        """
