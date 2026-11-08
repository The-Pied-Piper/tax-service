"""Application port for the ``TakeHomeCalculations`` tag.

The inbound adapter calls this; a service in `application/services` implements it.
`service-gen sync` never overwrites this file.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from app.domain.take_home import TakeHomeResult


class TakeHomeCalculationsPort(Protocol):
    async def compute_take_home_calculation(
        self,
        jurisdiction_code: str,
        year: int,
        salary: Decimal,
        language_code: str,
        include_trace: bool,
    ) -> TakeHomeResult: ...
