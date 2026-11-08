"""Persistence models (SQLAlchemy ORM). These are storage details, not domain objects.

Every table must subclass `Base` so Alembic autogenerate sees it; import new model
modules in `__init__.py` so they are registered before migrations run.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
