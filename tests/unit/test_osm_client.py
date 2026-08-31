"""
Unit tests for OsmApiClient — all network calls are mocked with httpx's
MockTransport so these tests run offline and never touch a live server.
"""

import httpx
import pytest

from src.external.water.osm_client import OsmApiClient, OsmUnavailableError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_SAMPLE_RESPONSE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="CGImap 0.9.3 (886105 spike-08.openstreetmap.org)" copyright="OpenStreetMap and contributors" attribution="http://www.openstreetmap.org/copyright" license="http://opendatacommons.org/licenses/odbl/1-0/">
 <node id="1" visible="true" version="1" changeset="1" timestamp="2010-01-01T00:00:00Z" user="test" uid="1" lat="21.0" lon="81.0"/>
 <node id="2" visible="true" version="1" changeset="1" timestamp="2010-01-01T00:00:00Z" user="test" uid="1" lat="21.1" lon="81.1"/>
 <way id="10" visible="true" version="1" changeset="1" timestamp="2010-01-01T00:00:00Z" user="test" uid="1">
  <nd ref="1"/>
  <nd ref="2"/>
  <tag k="waterway" v="river"/>
 </way>
</osm>
"""


# ---------------------------------------------------------------------------
# Successful query
# ---------------------------------------------------------------------------
class TestOsmApiClientSuccess:
    def test_returns_xml_on_200(self, monkeypatch):
        """Client should return the raw XML string on a 200 OK."""

        def mock_get(self_inner, url, **kwargs):
            return httpx.Response(
                200,
                content=_SAMPLE_RESPONSE_XML.encode(),
                request=httpx.Request("GET", url),
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        client = OsmApiClient(
            endpoint="https://fake-osm.example/api/0.6/map",
            timeout_s=5,
        )
        result = client.query_water_features(21.0, 81.0, 21.5, 81.5)
        assert "<osm" in result
        assert '<way id="10"' in result


# ---------------------------------------------------------------------------
# Failures and Retries
# ---------------------------------------------------------------------------
class TestOsmApiClientFailures:
    def test_raises_unavailable_when_all_retries_fail(self, monkeypatch):
        """API returns 503 — should retry then raise OsmUnavailableError."""

        def mock_get(self_inner, url, **kwargs):
            return httpx.Response(
                503,
                content=b"Service Unavailable",
                request=httpx.Request("GET", url),
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        client = OsmApiClient(
            endpoint="https://fake-osm.example/api/0.6/map",
            timeout_s=5,
        )
        # Using a very fast retry config for the test would be better, but since it's hardcoded in the decorator,
        # we just let it run. Wait, tenacity wait_exponential min=2 max=10 for 3 attempts = ~6 seconds total.
        with pytest.raises(OsmUnavailableError):
            client.query_water_features(21.0, 81.0, 21.5, 81.5)
