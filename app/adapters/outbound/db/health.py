"""Readiness probe for the database: `SELECT 1` on a pooled connection."""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.application.ports.health import NotReadyError


class DatabaseProbe:
    name = "database"

    def __init__(self, engine: AsyncEngine, timeout: float = 2.0) -> None:
        self._engine = engine
        self._timeout = timeout

    async def check(self) -> None:
        try:
            async with asyncio.timeout(self._timeout), self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError) as exc:  # TimeoutError is an OSError
            raise NotReadyError(f"{self.name}: {type(exc).__name__}") from exc
