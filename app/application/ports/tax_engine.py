"""Outbound port to the tax engine: the figures for one salary in one jurisdiction and year."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from app.domain.take_home import EngineFigures


class TaxEnginePort(Protocol):
    def compute(
        self, jurisdiction_code: str, year: int, salary: Decimal, with_trace: bool
    ) -> EngineFigures:
        """Run the engine; the trace is empty unless `with_trace`."""
