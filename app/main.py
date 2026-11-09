"""Composition root: builds services, wires them into request adapters, and creates the ASGI app.

This is the only place that knows about concrete implementations. Swap outbound
adapters (databases, clients) here, never inside the domain or application layers.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from connexion import AsyncApp
from connexion.resolver import Resolver
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.inbound import http_errors
from app.adapters.inbound.status_adapter import StatusRequestAdapter
from app.adapters.outbound.db import DatabaseProbe, create_engine
from app.application.services.status_service import StatusService
from app.generated.handlers import Adapters, build_operations
from app.settings import Settings

SPEC_PATH = Path(__file__).resolve().parent.parent / "openapi" / "openapi.yml"


def build_adapters(settings: Settings, engine: AsyncEngine) -> Adapters:
    """Construct outbound adapters -> services -> inbound request adapters.

    Repositories take a session factory from `create_session_factory(engine)`
    and are passed into the services they back.
    """
    probes = [DatabaseProbe(engine)]
    return Adapters(
        status=StatusRequestAdapter(StatusService(probes)),
    )


def create_app(settings: Settings | None = None) -> AsyncApp:
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level)
    engine = create_engine(settings)

    @asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    operations = build_operations(build_adapters(settings, engine))
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
