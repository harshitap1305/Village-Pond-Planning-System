"""
Unit tests for OsmApiClient and get_osm_client().

All network calls are mocked with monkeypatch so these tests run offline
and never touch a live server.

Module 7 additions:
  - no_retry_sleep fixture: patches tenacity.nap.sleep to prevent the test
    from waiting the real exponential-backoff delays (was ~6 s per test; would
    be ~45 s with TimeoutException retries without this fix).
  - test_retries_on_timeout_exception: verifies that TimeoutException (a
    TransportError subclass) is now retried — this was the critical Defect 1
    regression where single timeouts bypassed all retry attempts.
  - test_retries_on_connect_error: verifies ConnectError is also retried.
"""

import httpx
import pytest
import tenacity

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
# Fixture: suppress tenacity sleep to keep tests fast (Module 7 fix)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    """
    Patch tenacity's sleep so retry backoff doesn't actually wait.

    Without this, a 3-attempt test with wait_exponential_jitter(initial=2)
    would sleep ~4–6 s per test. With TimeoutException retries now enabled,
    that would be ~45 s for the worst-case NASA POWER test.
    """
    monkeypatch.setattr(tenacity.nap, "sleep", lambda _: None)


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
    def test_raises_unavailable_when_503(self, monkeypatch):
        """API returns 503 on every attempt → should raise OsmUnavailableError."""

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
        with pytest.raises(OsmUnavailableError):
            client.query_water_features(21.0, 81.0, 21.5, 81.5)

    def test_retries_on_timeout_exception(self, monkeypatch):
        """
        TimeoutException (TransportError subclass) MUST be retried 3×.

        Before Module 7 this bug caused a single timeout to bypass all retries
        and immediately surface as OsmUnavailableError.
        """
        call_count = [0]

        def mock_get(self_inner, url, **kwargs):
            call_count[0] += 1
            raise httpx.TimeoutException("timed out", request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        client = OsmApiClient(
            endpoint="https://fake-osm.example/api/0.6/map",
            timeout_s=1,
        )
        with pytest.raises(OsmUnavailableError):
            client.query_water_features(21.0, 81.0, 21.5, 81.5)

        assert (
            call_count[0] == 3
        ), f"Expected 3 retry attempts for TimeoutException, got {call_count[0]}"

    def test_retries_on_connect_error(self, monkeypatch):
        """
        ConnectError (TransportError subclass) MUST be retried 3×.
        """
        call_count = [0]

        def mock_get(self_inner, url, **kwargs):
            call_count[0] += 1
            raise httpx.ConnectError(
                "connection refused", request=httpx.Request("GET", url)
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        client = OsmApiClient(
            endpoint="https://fake-osm.example/api/0.6/map",
            timeout_s=1,
        )
        with pytest.raises(OsmUnavailableError):
            client.query_water_features(21.0, 81.0, 21.5, 81.5)

        assert (
            call_count[0] == 3
        ), f"Expected 3 retry attempts for ConnectError, got {call_count[0]}"

    def test_succeeds_on_retry_after_transient_failure(self, monkeypatch):
        """First attempt fails with 503, second succeeds — should return XML."""
        attempt = [0]

        def mock_get(self_inner, url, **kwargs):
            attempt[0] += 1
            if attempt[0] == 1:
                return httpx.Response(
                    503,
                    content=b"temporarily unavailable",
                    request=httpx.Request("GET", url),
                )
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
        assert attempt[0] == 2
