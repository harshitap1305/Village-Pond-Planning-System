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
"""

import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

_log = logging.getLogger(__name__)


class NasaPowerUnavailableError(Exception):
    """Raised when the NASA POWER API is unreachable after all retries."""

    pass


class NasaPowerClient:
    """
    Synchronous client for the NASA POWER Daily Point API (MERRA-2 backend).
    Intended to be run inside a threadpool executor by FastAPI async workers.
    """

    def __init__(self, endpoint: str, timeout_s: int = 30):
        self.endpoint = endpoint
        self.timeout = timeout_s
        self._client = httpx.Client(timeout=self.timeout)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def _fetch(self, url: str) -> str:
        """Internal GET with exponential backoff retry."""
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
            _log.warning("NASA POWER API failed: %s", exc)
            raise NasaPowerUnavailableError(
                f"NASA POWER API {self.endpoint} failed: {exc}"
            ) from exc
        except Exception as exc:
            _log.error("Unexpected error querying NASA POWER: %s", exc)
            raise NasaPowerUnavailableError(f"Unexpected error: {exc}") from exc
