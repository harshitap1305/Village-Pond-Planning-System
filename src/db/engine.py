"""
SQLAlchemy async engine and session factory for Module 8 — Persistence.

The engine is created lazily on first use (not at import time) so that the
application starts normally when DATABASE_URL is absent. All DB operations
are async (asyncpg driver); the engine is wired into FastAPI's lifespan.

Migration note:
    create_all() is used for v1 (single table, no production schema changes
    expected). When a second table is added, swap to Alembic:
      alembic init alembic
      alembic revision --autogenerate -m "add ..."
      alembic upgrade head
"""

import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

_log = logging.getLogger(__name__)

_engine = None
_async_session_factory = None


def init_engine(database_url: str) -> None:
    """
    Initialise the async engine. Called once from the FastAPI lifespan hook.
    No-op if already initialised.
    """
    global _engine, _async_session_factory
    if _engine is not None:
        return
    _engine = create_async_engine(
        database_url,
        echo=False,  # set True to log SQL in development
        pool_pre_ping=True,  # detect stale connections
        pool_size=5,
        max_overflow=10,
    )
    _async_session_factory = async_sessionmaker(
        _engine, class_=AsyncSession, expire_on_commit=False
    )
    _log.info("Database engine initialised: %s", database_url.split("@")[-1])


async def create_db_tables() -> None:
    """Create all SQLModel tables (IF NOT EXISTS). Called from lifespan."""
    if _engine is None:
        return
    async with _engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    _log.info("Database tables created/verified.")


async def dispose_engine() -> None:
    """Gracefully close the connection pool. Called from lifespan shutdown."""
    if _engine is not None:
        await _engine.dispose()
        _log.info("Database engine disposed.")


@asynccontextmanager
async def get_async_session():
    """Async context manager yielding an AsyncSession."""
    if _async_session_factory is None:
        raise RuntimeError("Database not configured (DATABASE_URL not set).")
    async with _async_session_factory() as session:
        yield session


def is_db_configured() -> bool:
    """True if init_engine() was successfully called."""
    return _engine is not None
