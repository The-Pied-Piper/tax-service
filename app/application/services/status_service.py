"""Health checks for the ``Status`` tag. Implements StatusPort.

Liveness always succeeds. Readiness runs every probe handed over by `main.py` and
fails with NotReadyError on the first unavailable dependency.
`service-gen sync` never overwrites this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.application.ports.health import Health, ReadinessProbe


class StatusService:
    def __init__(self, probes: Sequence[ReadinessProbe]) -> None:
        self._probes = probes

    async def get_livez(
        self,
    ) -> Health:
        return Health(status="ok")

    async def get_readyz(
        self,
    ) -> Health:
        for probe in self._probes:
            await probe.check()
        return Health(status="ok")
