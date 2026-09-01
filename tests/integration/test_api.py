from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app, raise_server_exceptions=False)
FIXTURE = Path("tests/fixtures/contours_1m.kml")


@pytest.mark.integration
def test_analyze_contour_success():
    """Full pipeline via HTTP — checks 200 and top-level JSON shape."""
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
    assert "candidate_locations" in body
    assert "selected_location" in body
    assert "catchment" in body
    assert "metadata" in body
    assert body["catchment"]["area_ha"] > 0


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
