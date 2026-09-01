from pathlib import Path

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_wrong_extension_returns_415():
    response = client.post(
        "/analyzeContour",
        files={"contour_map": ("upload.csv", b"dummy content", "text/csv")},
    )
    assert response.status_code == 415
    assert "Unsupported file type" in response.json()["detail"]


def test_malformed_xml_returns_400():
    response = client.post(
        "/analyzeContour",
        files={
            "contour_map": (
                "not_xml.kml",
                b"garbage bytes",
                "application/vnd.google-earth.kml+xml",
            )
        },
    )
    assert response.status_code == 400
    assert "KML file could not be parsed as XML" in response.json()["detail"]


def test_flat_terrain_returns_422():
    flat_kml_path = Path("tests/fixtures/flat_terrain.kml")
    response = client.post(
        "/analyzeContour",
        files={
            "contour_map": (
                "flat_terrain.kml",
                flat_kml_path.read_bytes(),
                "application/vnd.google-earth.kml+xml",
            )
        },
    )
    assert response.status_code == 422
    assert "same elevation" in response.json()["detail"]


def test_oversized_file_returns_413():
    # Simulate a large file by sending a fake Content-Length header
    # TestClient doesn't automatically compute Content-Length when files are provided,
    # but we can force a header to trigger the guard.
    response = client.post(
        "/analyzeContour",
        files={
            "contour_map": (
                "large.kml",
                b"dummy",
                "application/vnd.google-earth.kml+xml",
            )
        },
        headers={"Content-Length": str(25 * 1024 * 1024)},  # 25 MB
    )
    assert response.status_code == 413
    assert "exceeds the 20MB upload limit" in response.json()["detail"]
