import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

_log = logging.getLogger(__name__)


class OsmUnavailableError(Exception):
    """Raised when the OSM API is completely unreachable after retries."""

    pass


class OsmApiClient:
    """
    Synchronous client for querying the main OpenStreetMap (v0.6) API.
    Used within a threadpool by the FastAPI async worker.
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
    def _fetch_bbox(self, url: str) -> str:
        """
        Internal wrapper to execute the HTTP GET with exponential backoff.
        Raises httpx.HTTPError on failure.
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
            _log.warning("OSM API failed: %s", exc)
            raise OsmUnavailableError(f"OSM API {self.endpoint} failed: {exc}") from exc
        except Exception as exc:
            _log.error("Unexpected error querying OSM API: %s", exc)
            raise OsmUnavailableError(f"Unexpected error: {exc}") from exc
