"""A request the wire rules refuse but the application never sees."""


class InvalidRequestError(Exception):
    """A request value breaks a rule of the wire format; `field` names the request field."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
