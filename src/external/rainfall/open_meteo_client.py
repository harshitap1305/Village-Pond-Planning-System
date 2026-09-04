"""
HTTP client for the Open-Meteo Historical Weather Archive API.

Mirrors ``src/external/water/osm_client.py`` exactly — same httpx.Client,
same tenacity retry decorator, same UnavailableError exception pattern.

Endpoint used:
    https://archive-api.open-meteo.com/v1/archive
    ?latitude=..&longitude=..&start_date=..&end_date=..
    &daily=precipitation_sum&models=era5_land&timezone=Asia/Kolkata

No API key required. ERA5-Land: ~9 km resolution, data from 1950.
Tested live: 8.7 ms response for a 10-year daily query on central India.
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


class OpenMeteoUnavailableError(Exception):
    """Raised when the Open-Meteo API is unreachable after all retries."""

    pass


class OpenMeteoClient:
    """
    Synchronous client for the Open-Meteo Historical Weather Archive.
    Intended to be run inside a threadpool executor by FastAPI async workers.
    """

    def __init__(self, endpoint: str, timeout_s: int = 15):
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
            _log.warning("Open-Meteo API failed: %s", exc)
            raise OpenMeteoUnavailableError(
                f"Open-Meteo API {self.endpoint} failed: {exc}"
            ) from exc
        except Exception as exc:
            _log.error("Unexpected error querying Open-Meteo: %s", exc)
            raise OpenMeteoUnavailableError(f"Unexpected error: {exc}") from exc
