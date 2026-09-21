"""
HTTP client for the NASA POWER Daily Point API (fallback rainfall source).

Used automatically when Open-Meteo is unavailable. MERRA-2 reanalysis
(~50 km resolution) — coarser than ERA5-Land but independent data source.

Endpoint used:
    https://power.larc.nasa.gov/api/temporal/daily/point
    ?parameters=PRECTOTCORR&community=AG
    &latitude=..&longitude=..
    &start=YYYYMMDD&end=YYYYMMDD&format=JSON

No API key required for basic access.
Tested live: ~60 ms response. NASA uses PRECTOTCORR (bias-corrected mm/day).

Note: NASA POWER uses YYYYMMDD date format (not ISO 8601) in request params.
Response uses YYYYMMDD keys in the data dict. Fill value is -999.0 (not null).

Retry policy (Defect 1 fix):
  - Covers httpx.TransportError (TimeoutException, ConnectError, etc.) in
    addition to httpx.HTTPError. Previously only HTTPError was retried.
  - wait_exponential_jitter prevents thundering-herd under concurrent load.

Singleton pattern (Defect 4 fix):
  - get_nasa_power_client() returns a module-level singleton so httpx.Client's
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


class NasaPowerUnavailableError(Exception):
    """Raised when the NASA POWER API is unreachable after all retries."""

    pass


class NasaPowerClient:
    """
    Synchronous client for the NASA POWER Daily Point API (MERRA-2 backend).
    Intended to be run inside a threadpool executor by FastAPI async workers.

    Instantiate via :func:`get_nasa_power_client` to reuse the connection pool.
    """

    def __init__(self, endpoint: str, timeout_s: int = 30):
        self.endpoint = endpoint
        self.timeout = timeout_s
        # Granular timeout: short connect phase, longer read for MERRA-2 payloads.
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
        Query NASA POWER for daily corrected precipitation (PRECTOTCORR).

        Args:
            lat:        WGS84 latitude.
            lon:        WGS84 longitude.
            start_date: ISO 8601 date string "YYYY-MM-DD" — converted internally
                        to NASA POWER's YYYYMMDD format.
            end_date:   ISO 8601 date string "YYYY-MM-DD".

        Returns:
            Raw JSON string from the NASA POWER API.

        Raises:
            NasaPowerUnavailableError: if the API fails after all retries.
        """
        # NASA POWER requires YYYYMMDD format (not ISO 8601)
        start_ymd = start_date.replace("-", "")
        end_ymd = end_date.replace("-", "")

        url = (
            f"{self.endpoint}"
            f"?parameters=PRECTOTCORR"
            f"&community=AG"
            f"&latitude={lat}&longitude={lon}"
            f"&start={start_ymd}&end={end_ymd}"
            f"&format=JSON"
        )
        try:
            return self._fetch(url)
        except httpx.HTTPError as exc:
            _log.warning("NASA POWER API HTTP error: %s", exc)
            raise NasaPowerUnavailableError(
                f"NASA POWER API {self.endpoint} failed: {exc}"
            ) from exc
        except httpx.TransportError as exc:
            _log.warning("NASA POWER API transport error (timeout/connect): %s", exc)
            raise NasaPowerUnavailableError(
                f"NASA POWER API {self.endpoint} transport error: {exc}"
            ) from exc
        except Exception as exc:
            _log.error("Unexpected error querying NASA POWER: %s", exc)
            raise NasaPowerUnavailableError(f"Unexpected error: {exc}") from exc

    def close(self) -> None:
        """Close the underlying httpx connection pool."""
        self._client.close()

    def __enter__(self) -> "NasaPowerClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Module-level singleton — reuses the TCP connection pool across calls.
# ---------------------------------------------------------------------------
_nasa_power_client: NasaPowerClient | None = None


def get_nasa_power_client(endpoint: str, timeout_s: int) -> NasaPowerClient:
    """
    Return the module-level singleton NasaPowerClient, creating it on first call.

    Using a singleton reuses the httpx connection pool across requests instead
    of opening new TCP connections on every analysis run.
    """
    global _nasa_power_client
    if _nasa_power_client is None or _nasa_power_client.endpoint != endpoint:
        _nasa_power_client = NasaPowerClient(endpoint=endpoint, timeout_s=timeout_s)
    return _nasa_power_client
