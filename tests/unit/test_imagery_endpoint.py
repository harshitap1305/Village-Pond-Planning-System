"""
Unit tests for GET /api/imagery.
"""

from fastapi.testclient import TestClient

from src.api.imagery import get_available_providers
from src.api.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_default_returns_esri_satellite():
    resp = client.get("/api/imagery")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "esri_satellite"
    assert "url_template" in data
    assert "arcgisonline.com" in data["url_template"]
    assert "attribution" in data
    assert data["max_zoom"] >= 18


def test_carto_light_provider():
    resp = client.get("/api/imagery?provider=carto_light")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "carto_light"
    assert "cartocdn.com" in data["url_template"]
    assert data["subdomains"] == "abcd"


def test_osm_standard_provider():
    resp = client.get("/api/imagery?provider=osm_standard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "osm_standard"
    assert "openstreetmap.org" in data["url_template"]


def test_invalid_provider_returns_422():
    resp = client.get("/api/imagery?provider=google_maps")
    assert resp.status_code == 422


def test_bbox_echoed_in_response():
    bbox = "18.9,81.8,19.3,82.2"
    resp = client.get(f"/api/imagery?bbox={bbox}")
    assert resp.status_code == 200
    assert resp.json()["requested_bbox"] == bbox


def test_no_api_key_required_for_all_providers():
    for provider in get_available_providers():
        resp = client.get(f"/api/imagery?provider={provider}")
        assert resp.status_code == 200
        assert resp.json()["api_key_required"] is False


def test_all_providers_have_required_fields():
    required = {"url_template", "attribution", "max_zoom", "min_zoom", "provider"}
    for provider in get_available_providers():
        data = client.get(f"/api/imagery?provider={provider}").json()
        assert required.issubset(data.keys()), f"{provider} missing fields"
