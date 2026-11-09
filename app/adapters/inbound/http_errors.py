"""HTTP error responses: translates domain and application errors into problem+json.

Errors carry no HTTP knowledge; this inbound adapter owns the status codes and bodies.
`create_app` in `main.py` only registers it.
"""

from __future__ import annotations

from connexion import AsyncApp
from connexion.lifecycle import ConnexionRequest, ConnexionResponse
from connexion.problem import problem
from pydantic import ValidationError as PydanticValidationError

from app.application.ports.health import NotReadyError
from app.domain.errors import ConflictError, DomainError, NotFoundError, ValidationError

# Most specific first; DomainError is the fallback.
_DOMAIN_ERROR_STATUS: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    ValidationError: 422,
    DomainError: 400,
}


def register_error_handlers(app: AsyncApp) -> None:
    app.add_error_handler(DomainError, _domain_error)
    app.add_error_handler(PydanticValidationError, _bad_request)
    app.add_error_handler(NotReadyError, _not_ready)
    app.add_error_handler(NotImplementedError, _not_implemented)


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
