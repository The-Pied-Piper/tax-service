"""Readiness probes and the health report.

A probe is one per external dependency the service cannot work without.

`main.py` hands the probes to the health-check service; `adapters/outbound/db/health.py`
is the one for Postgres. Add more (caches, downstream APIs) the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Health:
    """What a liveness or readiness check reports: the status the health response carries."""

    status: str


class NotReadyError(Exception):
    """A dependency is unavailable. The inbound HTTP adapter translates this into a response."""


class ReadinessProbe(Protocol):
    name: str

    async def check(self) -> None:
        """Return when the dependency is reachable; raise NotReadyError otherwise."""
        ...
