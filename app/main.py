"""Composition root: builds services, wires them into request adapters, and creates the ASGI app.

This is the only place that knows about concrete implementations. Swap outbound
adapters (databases, clients) here, never inside the domain or application layers.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from connexion import AsyncApp
from connexion.resolver import Resolver
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.inbound import http_errors
from app.adapters.inbound.jurisdictions_adapter import JurisdictionsRequestAdapter
from app.adapters.inbound.status_adapter import StatusRequestAdapter
from app.adapters.inbound.take_home_calculations_adapter import TakeHomeCalculationsRequestAdapter
from app.adapters.outbound.db import create_engine
from app.adapters.outbound.tax_engine import TaxEngineDeductions
from app.application.services.jurisdictions_service import JurisdictionsService
from app.application.services.status_service import StatusService
from app.application.services.take_home_calculations_service import TakeHomeCalculationsService
from app.generated.handlers import Adapters, build_operations
from app.settings import Settings

SPEC_PATH = Path(__file__).resolve().parent.parent / "openapi" / "openapi.yml"


def build_adapters(settings: Settings, engine: AsyncEngine) -> Adapters:
    """Construct outbound adapters -> services -> inbound request adapters.

    Repositories take a session factory from `create_session_factory(engine)`
    and are passed into the services they back.
    """
    # No probes: this service keeps no state and uses no database, and on Lambda there
    # is none to reach, so a DatabaseProbe would hold /status/readyz at 503 for ever.
    # Pass probes here (the empty tuple below) when the service gains a dependency worth checking.
    return Adapters(
        jurisdictions=JurisdictionsRequestAdapter(JurisdictionsService()),
        status=StatusRequestAdapter(StatusService(())),
        take_home_calculations=TakeHomeCalculationsRequestAdapter(
            TakeHomeCalculationsService(TaxEngineDeductions())
        ),
    )


def create_app(
    settings: Settings | None = None,
    build: Callable[[Settings, AsyncEngine], Adapters] = build_adapters,
) -> AsyncApp:
    """The ASGI app; `build` replaces the wiring of `build_adapters` (a test seam)."""
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level)
    engine = create_engine(settings)

    @asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    operations = build_operations(build(settings, engine))
    app = AsyncApp(__name__, lifespan=lifespan)
    app.add_api(
        SPEC_PATH,
        resolver=Resolver(function_resolver=operations.__getitem__),
        pythonic_params=True,
        strict_validation=True,
        validate_responses=settings.validate_responses,
    )
    http_errors.register_error_handlers(app)
    return app


app = create_app()
