"""Readiness probes: one per external dependency the service cannot work without.

`main.py` hands the probes to the health-check service; `adapters/outbound/db/health.py`
is the one for Postgres. Add more (caches, downstream APIs) the same way.
"""

from __future__ import annotations

from typing import Protocol


class NotReadyError(Exception):
    """A dependency is unavailable. `main.py` maps this to HTTP 503."""


class ReadinessProbe(Protocol):
    name: str

    async def check(self) -> None:
        """Return when the dependency is reachable; raise NotReadyError otherwise."""
        ...
