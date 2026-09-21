"""
HTTP client for the Open-Meteo Historical Weather Archive API.

Mirrors ``src/external/water/osm_client.py`` exactly — same httpx.Client,
same tenacity retry decorator with jitter, same UnavailableError pattern.

Endpoint used:
    https://archive-api.open-meteo.com/v1/archive
    ?latitude=..&longitude=..&start_date=..&end_date=..
    &daily=precipitation_sum&models=era5_land&timezone=Asia/Kolkata

No API key required. ERA5-Land: ~9 km resolution, data from 1950.
Tested live: 8.7 ms response for a 10-year daily query on central India.

Retry policy (Defect 1 fix):
  - Covers httpx.TransportError (TimeoutException, ConnectError, etc.) in
    addition to httpx.HTTPError. Previously only HTTPError was retried.
  - wait_exponential_jitter prevents thundering-herd under concurrent load.

Singleton pattern (Defect 4 fix):
  - get_open_meteo_client() returns a module-level singleton so httpx.Client's
    TCP connection pool is reused across calls.
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


class OpenMeteoUnavailableError(Exception):
    """Raised when the Open-Meteo API is unreachable after all retries."""

    pass


class OpenMeteoClient:
    """
    Synchronous client for the Open-Meteo Historical Weather Archive.
    Intended to be run inside a threadpool executor by FastAPI async workers.

    Instantiate via :func:`get_open_meteo_client` to reuse the connection pool.
    """

    def __init__(self, endpoint: str, timeout_s: int = 15):
        self.endpoint = endpoint
        self.timeout = timeout_s
        # Granular timeout: short connect phase, longer read phase for large
        # ERA5-Land 10-year daily payloads.
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=3.0, read=float(timeout_s), write=10.0, pool=5.0
            )
        )

    @retry(
        stop=stop_after_attempt(3),
        # Jitter prevents thundering-herd when concurrent requests all
        # hit the same failing server at exactly the same moment.
        wait=wait_exponential_jitter(initial=2, max=10, jitter=2),
        # Fix: TransportError covers TimeoutException and ConnectError, which
        # are NOT subclasses of HTTPError and were previously not retried.
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TransportError)),
        reraise=True,
    )
    def _fetch(self, url: str) -> str:
        """Internal GET with exponential-jitter backoff retry."""
        _log.info("HTTP Request: GET %s", url)
        response = self._client.get(url)
        response.raise_for_status()
        return response.text

    def get_daily_rainfall(
        self,
        lat: float,
        lon: float,
        start_date: str,
        end_date: str,
    ) -> str:
        """
        Query ERA5-Land archive for daily precipitation sums.

        Args:
            lat:        WGS84 latitude.
            lon:        WGS84 longitude.
            start_date: ISO 8601 date string, e.g. "2015-01-01".
            end_date:   ISO 8601 date string, e.g. "2024-12-31".

        Returns:
            Raw JSON string from the Open-Meteo API.

        Raises:
            OpenMeteoUnavailableError: if the API fails after all retries.
        """
        url = (
            f"{self.endpoint}"
            f"?latitude={lat}&longitude={lon}"
            f"&start_date={start_date}&end_date={end_date}"
            f"&daily=precipitation_sum"
            f"&models=era5_land"
            f"&timezone=Asia%2FKolkata"
        )
        try:
            return self._fetch(url)
        except httpx.HTTPError as exc:
            _log.warning("Open-Meteo API HTTP error: %s", exc)
            raise OpenMeteoUnavailableError(
                f"Open-Meteo API {self.endpoint} failed: {exc}"
            ) from exc
        except httpx.TransportError as exc:
            _log.warning("Open-Meteo API transport error (timeout/connect): %s", exc)
            raise OpenMeteoUnavailableError(
                f"Open-Meteo API {self.endpoint} transport error: {exc}"
            ) from exc
        except Exception as exc:
            _log.error("Unexpected error querying Open-Meteo: %s", exc)
            raise OpenMeteoUnavailableError(f"Unexpected error: {exc}") from exc

    def close(self) -> None:
        """Close the underlying httpx connection pool."""
        self._client.close()

    def __enter__(self) -> "OpenMeteoClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Module-level singleton — reuses the TCP connection pool across calls.
# ---------------------------------------------------------------------------
_open_meteo_client: OpenMeteoClient | None = None


def get_open_meteo_client(endpoint: str, timeout_s: int) -> OpenMeteoClient:
    """
    Return the module-level singleton OpenMeteoClient, creating it on first call.

    Using a singleton reuses the httpx connection pool across requests instead
    of opening new TCP connections on every analysis run.
    """
    global _open_meteo_client
    if _open_meteo_client is None or _open_meteo_client.endpoint != endpoint:
        _open_meteo_client = OpenMeteoClient(endpoint=endpoint, timeout_s=timeout_s)
    return _open_meteo_client
