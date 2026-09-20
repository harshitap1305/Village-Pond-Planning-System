"""
Integration tests for the FastAPI HTTP layer (POST /analyzeContour).

These tests exercise the full request/response cycle via TestClient (ASGI).
All external API calls (OSM Overpass, Open-Meteo, NASA POWER) are mocked so
the suite runs offline and deterministically.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app, raise_server_exceptions=False)
FIXTURE = Path("tests/fixtures/contours_1m.kml")

# ---------------------------------------------------------------------------
# Shared API mocks — same fixture values used in test_full_pipeline.py so
# results are comparable across test modules.
# ---------------------------------------------------------------------------
_EMPTY_OSM = '<?xml version="1.0" encoding="UTF-8"?><osm version="0.6"></osm>'
_MOCK_RAINFALL = json.dumps(
    {
        "daily": {
            # Jul: 800mm, Aug: 750mm (both > Ia=20.76mm → produce runoff)
            # Nov: 10mm (< Ia → zero runoff)
            # annual_avg_mm=1560, wet_season=1550, dry_season=10
            "time": ["2023-07-15", "2023-08-15", "2023-11-15"],
            "precipitation_sum": [800.0, 750.0, 10.0],
        }
    }
)


def _post_fixture_file():
    """Helper: POST contours_1m.kml with external APIs mocked."""
    with (
        patch(
            "src.catchment.water_exclusion.OsmApiClient.query_water_features",
            return_value=_EMPTY_OSM,
        ),
        patch(
            "src.catchment.rainfall_service.OpenMeteoClient.get_daily_rainfall",
            return_value=_MOCK_RAINFALL,
        ),
    ):
        with open(FIXTURE, "rb") as f:
            return client.post(
                "/analyzeContour",
                files={
                    "contour_map": (
                        "contours_1m.kml",
                        f,
                        "application/vnd.google-earth.kml+xml",
                    )
                },
            )


@pytest.mark.integration
def test_analyze_contour_success():
    """Full pipeline via HTTP — checks 200 status and all module output fields."""
    response = _post_fixture_file()

    assert response.status_code == 200
    body = response.json()

    # Core topology
    assert "candidate_locations" in body
    assert "selected_location" in body
    assert "catchment" in body
    assert "metadata" in body
    assert body["catchment"]["area_ha"] > 0

    # Module 5 operational metadata
    assert "warnings" in body
    assert isinstance(body["warnings"], list)
    assert body["metadata"]["processing_time_ms"] > 0

    # Module 2 — rainfall
    assert "rainfall" in body
    assert body["rainfall"] is not None
    assert body["rainfall"]["annual_avg_mm"] > 0

    # Module 3 — runoff
    assert "runoff" in body
    assert body["runoff"] is not None
    assert body["runoff"]["annual_avg_m3"] > 0

    # Module 4 — pond design
    assert "pond_design" in body
    assert body["pond_design"] is not None
    assert 1.5 <= body["pond_design"]["water_depth_m"] <= 4.0


@pytest.mark.integration
def test_analyze_contour_with_rainfall_unavailable():
    """
    When rainfall data is completely unavailable, the pipeline must still return 200.

    We patch ``build_rainfall_stats`` directly to return None (simulating both
    Open-Meteo and NASA POWER failing after retries). This avoids a cache-hit
    from the previous test — the in-memory ``_rainfall_cache`` is bypassed
    entirely since we stub the public interface, not the underlying clients.

    Expected behaviour:
    - ``rainfall``, ``runoff``, and ``pond_design`` are all null.
    - ``warnings`` contains the three expected machine-readable codes.
    """
    with (
        patch(
            "src.catchment.water_exclusion.OsmApiClient.query_water_features",
            return_value=_EMPTY_OSM,
        ),
        # Patch the public interface — bypasses the cache and all client logic.
        patch(
            "src.api.analysis_service.build_rainfall_stats",
            return_value=None,
        ),
    ):
        with open(FIXTURE, "rb") as f:
            response = client.post(
                "/analyzeContour",
                files={
                    "contour_map": (
                        "contours_1m.kml",
                        f,
                        "application/vnd.google-earth.kml+xml",
                    )
                },
            )

    assert response.status_code == 200
    body = response.json()

    # Hydrological fields must be null
    assert body["rainfall"] is None
    assert body["runoff"] is None
    assert body["pond_design"] is None

    # Warnings must list all three degraded steps
    assert "rainfall_unavailable" in body["warnings"]
    assert "runoff_unavailable" in body["warnings"]
    assert "pond_design_unavailable" in body["warnings"]

    # Core topology must still be present
    assert body["catchment"]["area_ha"] > 0
    assert body["metadata"]["processing_time_ms"] > 0


def test_analyze_contour_bad_xml_returns_400():
    response = client.post(
        "/analyzeContour",
        files={
            "contour_map": (
                "broken.kmz",
                b"not xml at all",
                "application/vnd.google-earth.kml+xml",
            )
        },
    )
    assert response.status_code == 400


def test_analyze_contour_wrong_extension_returns_415():
    response = client.post(
        "/analyzeContour",
        files={"contour_map": ("data.csv", b"a,b,c", "text/csv")},
    )
    assert response.status_code == 415
