"""
Unit tests for NasaPowerClient and get_nasa_power_client().

All network calls are mocked with monkeypatch so these tests run offline.

Covers:
  - Successful 200 response
  - 503 status → retried 3× → NasaPowerUnavailableError
  - TimeoutException → retried 3× → NasaPowerUnavailableError (Defect 1 fix)
  - ConnectError → retried 3× → NasaPowerUnavailableError (Defect 1 fix)
  - Unexpected exception → NasaPowerUnavailableError
  - URL format verification (YYYYMMDD, PRECTOTCORR, community=AG)
  - Transient failure recovery (1st attempt fails, 2nd succeeds)
  - Singleton getter returns same instance for same endpoint
"""

import httpx
import pytest
import tenacity

from src.external.rainfall.nasa_power_client import (
    NasaPowerClient,
    NasaPowerUnavailableError,
    get_nasa_power_client,
)

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------
_SAMPLE_RESPONSE = (
    '{"properties":{"parameter":{"PRECTOTCORR":{"20230101":3.2,"20230102":0.0}}}}'
)

_ENDPOINT = "https://fake-nasa-power.example/api/temporal/daily/point"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    """Patch tenacity.nap.sleep so retry backoff doesn't actually wait."""
    monkeypatch.setattr(tenacity.nap, "sleep", lambda _: None)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the module-level singleton between tests."""
    import src.external.rainfall.nasa_power_client as mod

    original = mod._nasa_power_client
    yield
    mod._nasa_power_client = original


# ---------------------------------------------------------------------------
# Successful query
# ---------------------------------------------------------------------------
class TestNasaPowerClientSuccess:
    def test_returns_json_on_200(self, monkeypatch):
        """Client returns raw JSON string on a 200 OK."""

        def mock_get(self_inner, url, **kwargs):
            return httpx.Response(
                200,
                content=_SAMPLE_RESPONSE.encode(),
                request=httpx.Request("GET", url),
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        client = NasaPowerClient(endpoint=_ENDPOINT, timeout_s=5)
        result = client.get_daily_rainfall(22.0, 81.0, "2023-01-01", "2023-12-31")
        assert "PRECTOTCORR" in result

    def test_url_uses_yyyymmdd_format(self, monkeypatch):
        """NASA POWER requires YYYYMMDD; ISO 8601 input must be converted."""
        captured_url = []

        def mock_get(self_inner, url, **kwargs):
            captured_url.append(url)
            return httpx.Response(
                200,
                content=_SAMPLE_RESPONSE.encode(),
                request=httpx.Request("GET", url),
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        client = NasaPowerClient(endpoint=_ENDPOINT, timeout_s=5)
        client.get_daily_rainfall(22.5, 80.3, "2023-01-01", "2023-12-31")

        url = captured_url[0]
        assert "start=20230101" in url
        assert "end=20231231" in url
        assert "PRECTOTCORR" in url
        assert "community=AG" in url
        assert "latitude=22.5" in url
        assert "longitude=80.3" in url

    def test_iso8601_dashes_stripped(self, monkeypatch):
        """Any ISO 8601 date string must have dashes removed for NASA POWER."""
        captured_url = []

        def mock_get(self_inner, url, **kwargs):
            captured_url.append(url)
            return httpx.Response(
                200,
                content=_SAMPLE_RESPONSE.encode(),
                request=httpx.Request("GET", url),
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        client = NasaPowerClient(endpoint=_ENDPOINT, timeout_s=5)
        client.get_daily_rainfall(22.0, 81.0, "2015-06-15", "2024-09-30")
        assert "start=20150615" in captured_url[0]
        assert "end=20240930" in captured_url[0]


# ---------------------------------------------------------------------------
# Failures and Retries
# ---------------------------------------------------------------------------
class TestNasaPowerClientFailures:
    def test_503_raises_unavailable(self, monkeypatch):
        """503 on every attempt → NasaPowerUnavailableError after 3 retries."""

        def mock_get(self_inner, url, **kwargs):
            return httpx.Response(
                503, content=b"down", request=httpx.Request("GET", url)
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        client = NasaPowerClient(endpoint=_ENDPOINT, timeout_s=5)
        with pytest.raises(NasaPowerUnavailableError):
            client.get_daily_rainfall(22.0, 81.0, "2023-01-01", "2023-12-31")

    def test_timeout_exception_is_retried(self, monkeypatch):
        """
        TimeoutException MUST be retried 3× (Defect 1 fix).
        Before Module 7, a single timeout bypassed all retry attempts.
        """
        call_count = [0]

        def mock_get(self_inner, url, **kwargs):
            call_count[0] += 1
            raise httpx.TimeoutException("timed out", request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        client = NasaPowerClient(endpoint=_ENDPOINT, timeout_s=1)
        with pytest.raises(NasaPowerUnavailableError):
            client.get_daily_rainfall(22.0, 81.0, "2023-01-01", "2023-12-31")

        assert (
            call_count[0] == 3
        ), f"Expected 3 retry attempts for TimeoutException, got {call_count[0]}"

    def test_connect_error_is_retried(self, monkeypatch):
        """ConnectError MUST be retried 3× (Defect 1 fix)."""
        call_count = [0]

        def mock_get(self_inner, url, **kwargs):
            call_count[0] += 1
            raise httpx.ConnectError(
                "connection refused", request=httpx.Request("GET", url)
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        client = NasaPowerClient(endpoint=_ENDPOINT, timeout_s=1)
        with pytest.raises(NasaPowerUnavailableError):
            client.get_daily_rainfall(22.0, 81.0, "2023-01-01", "2023-12-31")

        assert (
            call_count[0] == 3
        ), f"Expected 3 retry attempts for ConnectError, got {call_count[0]}"

    def test_unexpected_exception_raises_unavailable(self, monkeypatch):
        """Non-httpx exception is wrapped in NasaPowerUnavailableError."""

        def mock_get(self_inner, url, **kwargs):
            raise RuntimeError("unexpected internal error")

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        client = NasaPowerClient(endpoint=_ENDPOINT, timeout_s=1)
        with pytest.raises(NasaPowerUnavailableError):
            client.get_daily_rainfall(22.0, 81.0, "2023-01-01", "2023-12-31")

    def test_succeeds_on_retry_after_transient_503(self, monkeypatch):
        """First attempt fails with 503, second succeeds — should return JSON."""
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
                content=_SAMPLE_RESPONSE.encode(),
                request=httpx.Request("GET", url),
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        client = NasaPowerClient(endpoint=_ENDPOINT, timeout_s=5)
        result = client.get_daily_rainfall(22.0, 81.0, "2023-01-01", "2023-12-31")
        assert "PRECTOTCORR" in result
        assert attempt[0] == 2


# ---------------------------------------------------------------------------
# Singleton getter
# ---------------------------------------------------------------------------
class TestGetNasaPowerClient:
    def test_returns_same_instance_for_same_endpoint(self):
        """Singleton getter returns the same object on repeated calls."""
        import src.external.rainfall.nasa_power_client as mod

        mod._nasa_power_client = None
        a = get_nasa_power_client(endpoint=_ENDPOINT, timeout_s=30)
        b = get_nasa_power_client(endpoint=_ENDPOINT, timeout_s=30)
        assert a is b

    def test_creates_new_instance_for_different_endpoint(self):
        """Different endpoint → new client."""
        import src.external.rainfall.nasa_power_client as mod

        mod._nasa_power_client = None
        a = get_nasa_power_client(endpoint=_ENDPOINT, timeout_s=30)
        b = get_nasa_power_client(endpoint="https://other-endpoint/", timeout_s=30)
        assert a is not b
