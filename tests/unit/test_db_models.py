"""
Unit tests for AnalysisRun model.

Uses in-memory SQLite so no live Postgres is required for these unit tests.
Verifies model fields, UUID default, and JSONB-like dict storage via
SQLite's JSON column type handling.
"""

import uuid
from datetime import datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.db.models import AnalysisRun


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def test_analysis_run_insert_and_retrieve(session):
    payload = {"candidate_locations": [], "warnings": ["test"]}
    run = AnalysisRun(filename="test.kml", result_json=payload)
    session.add(run)
    session.commit()
    session.refresh(run)

    assert isinstance(run.id, uuid.UUID)
    assert run.filename == "test.kml"
    assert run.result_json == payload
    assert isinstance(run.created_at, datetime)


def test_analysis_run_id_is_unique(session):
    r1 = AnalysisRun(filename="a.kml", result_json={})
    r2 = AnalysisRun(filename="b.kml", result_json={})
    session.add(r1)
    session.add(r2)
    session.commit()
    assert r1.id != r2.id


def test_result_id_in_analysis_result_schema():
    """AnalysisResult.result_id is optional and defaults to None."""
    from src.schemas.response import AnalysisResult

    # result_id is optional — existing callers unaffected
    assert AnalysisResult.model_fields["result_id"].is_required() is False
