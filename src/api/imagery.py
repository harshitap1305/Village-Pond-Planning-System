"""
GET /imagery — returns tile URL metadata for map baselayers.

The frontend fetches this on init to build Leaflet tile layers dynamically,
rather than hardcoding tile URLs in the JS bundle. Swapping providers or
updating attribution only requires a backend change.
"""

from fastapi import APIRouter, Query

router = APIRouter()

# ── Provider registry ──────────────────────────────────────────────────────────
# Each entry defines the full Leaflet-compatible tile descriptor.
# url_template uses {z}/{x}/{y} or {z}/{x}/{y}{r} (retina suffix).
_PROVIDERS: dict[str, dict] = {
    "esri_satellite": {
        "label": "Esri World Imagery (Satellite)",
        "url_template": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        "attribution": (
            "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, "
            "and the GIS User Community"
        ),
        "max_zoom": 19,
        "min_zoom": 0,
        "subdomains": "",
        "api_key_required": False,
    },
    "carto_light": {
        "label": "CartoDB Positron (Street)",
        "url_template": (
            "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        ),
        "attribution": (
            "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> "
            "contributors &copy; <a href='https://carto.com/attributions'>CARTO</a>"
        ),
        "max_zoom": 20,
        "min_zoom": 0,
        "subdomains": "abcd",
        "api_key_required": False,
    },
    "osm_standard": {
        "label": "OpenStreetMap Standard",
        "url_template": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": (
            "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors"
        ),
        "max_zoom": 19,
        "min_zoom": 0,
        "subdomains": "abc",
        "api_key_required": False,
    },
}


@router.get(
    "/imagery",
    summary="Get basemap tile metadata for the frontend map",
    description=(
        "Returns a tile URL template and attribution string for the requested "
        "map provider. The frontend uses this to build Leaflet tile layers "
        "dynamically. Providers require no API keys."
    ),
    responses={
        422: {"description": "Unknown provider — must be one of the supported values"},
    },
)
async def get_imagery_metadata(
    provider: str = Query(
        default="esri_satellite",
        description=(
            "Tile provider key. One of: `esri_satellite`, `carto_light`, `osm_standard`."
        ),
    ),
    bbox: str | None = Query(
        default=None,
        description=(
            "Optional bounding box of the current map view: `south,west,north,east` "
            "in WGS84 decimal degrees. Echoed back in the response for cache-key use; "
            "does not alter the tile URL."
        ),
    ),
):
    """
    Return tile metadata for one of three supported basemap providers.

    - **esri_satellite** (default) — Esri World Imagery, best visual quality for site review
    - **carto_light** — CartoDB Positron light streets, good for annotation overlays
    - **osm_standard** — OpenStreetMap Carto, the classic base layer

    All providers are free and require no API key.
    """
    if provider not in _PROVIDERS:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown provider '{provider}'. "
                f"Valid options: {', '.join(_PROVIDERS.keys())}"
            ),
        )

    return {
        "provider": provider,
        **_PROVIDERS[provider],
        "requested_bbox": bbox,
    }


def get_available_providers() -> list[str]:
    """Helper used by tests to enumerate valid provider keys."""
    return list(_PROVIDERS.keys())
