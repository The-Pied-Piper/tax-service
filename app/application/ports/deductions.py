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
        items: tuple[str, ...],
        with_trace: bool,
    ) -> Deductions:
        """What `salary` pays of each of `items`, with the explaining trace (empty unless
        `with_trace`). Returns exactly one figure for each requested item.

        Raises InvalidArgumentError for a value the calculator cannot take, such as a language
        it cannot write, and DeductionsUnavailableError when an item is unknown to it or the
        calculation itself fails.
        """
