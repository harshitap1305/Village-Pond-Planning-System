"""
SQLModel database table for Module 8 — Persistence.

Design choice: one table, full AnalysisResult stored as JSONB.
See implementation_plan.md § Decision 1 for the full rationale.

PostgreSQL JSONB notes:
  - Stored in a binary decomposed form (faster to query than TEXT JSON).
  - Supports GIN indexing on individual JSON keys if needed later.
  - The 'result_json' column stores the exact dict that AnalysisResult.model_dump()
    produces — round-tripping is lossless via AnalysisResult.model_validate().
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, SQLModel


class JSONVariant(TypeDecorator):
    """
    Use native JSONB for PostgreSQL (faster, indexable) and standard JSON
    for SQLite (so in-memory unit tests don't crash with CompileError).
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class AnalysisRun(SQLModel, table=True):
    """One row per completed /analyzeContour request."""

    __tablename__ = "analysis_run"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Stable UUID identifier returned to the caller in the response.",
    )
    filename: str = Field(
        max_length=255,
        description="Original uploaded filename (e.g. 'contours.1m.kml').",
    )
    result_json: dict = Field(
        sa_column=Column(JSONVariant, nullable=False),
        description="Full AnalysisResult.model_dump() output stored as PostgreSQL JSONB.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the analysis completed.",
    )


class Village(SQLModel, table=True):
    """Seedable registry of villages for quick selection."""

    __tablename__ = "village"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    name: str = Field(index=True, max_length=255)
    state: str = Field(max_length=255)
    district: str = Field(max_length=255)
    latitude: float
    longitude: float
    kml_path: str = Field(
        description="Path to static KML file relative to project root"
    )
