"""
HTTP client for the main OpenStreetMap API (v0.6).

Mirrors the Open-Meteo and NASA POWER clients exactly — same httpx.Client,
same tenacity retry decorator with jitter, same UnavailableError pattern.

Retry policy (Defect 1 fix):
  - Covers httpx.TransportError (TimeoutException, ConnectError, etc.) in
    addition to httpx.HTTPError (4xx/5xx status codes).  Previously only
    HTTPError was retried; a single TCP timeout bypassed all retries.
  - wait_exponential_jitter prevents thundering-herd when multiple concurrent
    requests all hit the same failing server.

Singleton pattern (Defect 4 fix):
  - get_osm_client() returns a module-level singleton so httpx.Client's TCP
    connection pool is reused across calls instead of leaking sockets.
"""

import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

_log = logging.getLogger(__name__)


class OsmUnavailableError(Exception):
    """Raised when the OSM API is completely unreachable after retries."""

    pass


class OsmApiClient:
    """
    Synchronous client for querying the main OpenStreetMap (v0.6) API.
    Used within a threadpool by the FastAPI async worker.

    Instantiate via :func:`get_osm_client` to reuse the connection pool.
    """

    def __init__(self, endpoint: str, timeout_s: int = 15):
        self.endpoint = endpoint
        self.timeout = timeout_s
        # Granular timeout: short connect phase, longer read phase.
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=3.0, read=float(timeout_s), write=10.0, pool=5.0
            )
        )

    @retry(
        stop=stop_after_attempt(3),
        # Jitter prevents thundering-herd when multiple concurrent requests
        # all hit the same failing server at the same instant.
        wait=wait_exponential_jitter(initial=2, max=10, jitter=2),
        # Fix: TransportError covers TimeoutException and ConnectError, which
        # are NOT subclasses of HTTPError and were previously not retried.
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TransportError)),
        reraise=True,
    )
    def _fetch_bbox(self, url: str) -> str:
        """
        Internal wrapper to execute the HTTP GET with exponential-jitter backoff.
        Raises httpx.HTTPError or httpx.TransportError on failure (reraised by tenacity).
        """
        _log.info("HTTP Request: GET %s", url)
        response = self._client.get(url)
        response.raise_for_status()
        return response.text

    def query_water_features(
        self, south: float, west: float, north: float, east: float
    ) -> str:
        """
        Query the OSM API for all features within the given WGS84 bounding box.

        Returns:
            The raw OSM XML string.
        Raises:
            OsmUnavailableError: if the API request fails after all retries.
        """
        # The OSM API expects the bbox as: left,bottom,right,top (west,south,east,north)
        bbox_str = f"{west},{south},{east},{north}"
        url = f"{self.endpoint}?bbox={bbox_str}"

        try:
            return self._fetch_bbox(url)
        except httpx.HTTPError as exc:
            _log.warning("OSM API HTTP error: %s", exc)
            raise OsmUnavailableError(f"OSM API {self.endpoint} failed: {exc}") from exc
        except httpx.TransportError as exc:
            _log.warning("OSM API transport error (timeout/connect): %s", exc)
            raise OsmUnavailableError(
                f"OSM API {self.endpoint} transport error: {exc}"
            ) from exc
        except Exception as exc:
            _log.error("Unexpected error querying OSM API: %s", exc)
            raise OsmUnavailableError(f"Unexpected error: {exc}") from exc

    def close(self) -> None:
        """Close the underlying httpx connection pool."""
        self._client.close()

    def __enter__(self) -> "OsmApiClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Module-level singleton — reuses the TCP connection pool across calls.
# endpoint and timeout_s are compared on each call; if they differ (e.g. due
# to a settings override in tests) a new client is created.
# ---------------------------------------------------------------------------
_osm_client: OsmApiClient | None = None


def get_osm_client(endpoint: str, timeout_s: int) -> OsmApiClient:
    """
    Return the module-level singleton OsmApiClient, creating it on first call.

    Using a singleton reuses the httpx connection pool across requests instead
    of opening new TCP connections (and leaking sockets) on every analysis run.
    """
    global _osm_client
    if _osm_client is None or _osm_client.endpoint != endpoint:
        _osm_client = OsmApiClient(endpoint=endpoint, timeout_s=timeout_s)
    return _osm_client
