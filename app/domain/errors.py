"""Errors raised by the domain and application layers.

They carry no transport knowledge: the inbound adapter translates them into responses.
"""


class DomainError(Exception):
    """Base class for all business-rule violations."""


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class ValidationError(DomainError):
    pass


class InvalidArgumentError(DomainError):
    """A request value is invalid or not supported; `field` names the request field at fault."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
