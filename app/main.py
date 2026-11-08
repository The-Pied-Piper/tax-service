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
from connexion.lifecycle import ConnexionRequest, ConnexionResponse
from connexion.problem import problem
from connexion.resolver import Resolver
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.inbound.status_adapter import StatusRequestAdapter
from app.adapters.inbound.widgets_adapter import WidgetsRequestAdapter
from app.adapters.outbound.db import DatabaseProbe, create_engine
from app.application.ports.health import NotReadyError
from app.application.services.status_service import StatusService
from app.application.services.widgets_service import WidgetsService
from app.domain.errors import ConflictError, DomainError, NotFoundError, ValidationError
from app.generated.handlers import Adapters, build_operations
from app.settings import Settings

SPEC_PATH = Path(__file__).resolve().parent.parent / "openapi" / "openapi.yml"

# Most specific first; DomainError is the fallback.
_DOMAIN_ERROR_STATUS: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    ValidationError: 422,
    DomainError: 400,
}


def build_adapters(settings: Settings, engine: AsyncEngine) -> Adapters:
    """Construct outbound adapters -> services -> inbound request adapters.

    Repositories take a session factory from `create_session_factory(engine)`
    and are passed into the services they back.
    """
    probes = [DatabaseProbe(engine)]
    return Adapters(
        status=StatusRequestAdapter(StatusService(probes)),
        widgets=WidgetsRequestAdapter(WidgetsService()),
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
    app.add_error_handler(DomainError, _domain_error)
    app.add_error_handler(PydanticValidationError, _bad_request)
    app.add_error_handler(NotReadyError, _not_ready)
    app.add_error_handler(NotImplementedError, _not_implemented)
    return app


def _domain_error(request: ConnexionRequest, exc: Exception) -> ConnexionResponse:
    status = next(code for cls, code in _DOMAIN_ERROR_STATUS.items() if isinstance(exc, cls))
    return problem(status=status, title=type(exc).__name__, detail=str(exc))


def _bad_request(request: ConnexionRequest, exc: Exception) -> ConnexionResponse:
    """Handler-level coercion failed (e.g. a path param that is not a valid UUID)."""
    assert isinstance(exc, PydanticValidationError)
    detail = "; ".join(
        f"{'.'.join(map(str, e['loc'])) or 'value'}: {e['msg']}" for e in exc.errors()
    )
    return problem(status=400, title="Bad Request", detail=detail)


def _not_ready(request: ConnexionRequest, exc: Exception) -> ConnexionResponse:
    return problem(status=503, title="Service Unavailable", detail=str(exc))


def _not_implemented(request: ConnexionRequest, exc: Exception) -> ConnexionResponse:
    return problem(status=501, title="Not Implemented", detail=str(exc))


app = create_app()
