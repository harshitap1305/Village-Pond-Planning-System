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

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


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
        sa_column=Column(JSONB, nullable=False),
        description="Full AnalysisResult.model_dump() output stored as PostgreSQL JSONB.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the analysis completed.",
    )
