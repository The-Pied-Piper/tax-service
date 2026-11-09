"""Driven port: what a salary costs in contributions and tax in one jurisdiction and year."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from app.domain.take_home import Deductions


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

        Raises DeductionsUnavailableError when an item or the language is unknown to it or the
        calculation itself fails.
        """
