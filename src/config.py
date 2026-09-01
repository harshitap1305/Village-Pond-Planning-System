"""
Central configuration for the Village Pond Planning System.

All values can be overridden via environment variables or a .env file.
This enforces the 12-factor app principle: no hard-coded config anywhere in src/.

Usage:
    from src.config import settings
    cell_size = settings.cell_size_m
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Environment ─────────────────────────────────────────────────────────
    env: str = "dev"
    log_level: str = "INFO"

    # ── API ──────────────────────────────────────────────────────────────────
    api_title: str = "Village Pond Planning API"
    api_version: str = "0.1.0"
    port: int = 8000

    # ── File Upload Limits ────────────────────────────────────────────────────
    max_upload_mb: int = 20
    allowed_extensions: list[str] = [".kml", ".kmz"]

    # ── DEM Construction (Module 5) ───────────────────────────────────────────
    # Grid cell size in metres. Smaller = finer terrain model, slower to build.
    cell_size_m: float = 2.0
    # Extra padding around the bounding box so edge contour points aren't clipped.
    dem_buffer_cells: int = 2

    # ── Candidate Detection (Module 9 — Depression Method) ───────────────────
    # Minimum fill depth (metres) for a cell to count as a real depression.
    # Eliminates IDW interpolation numerical noise (spurious sub-pixel pits).
    min_depression_depth_m: float = 0.1

    # Minimum depression footprint area (m²) — filters sub-grid noise.
    # At 2m cell size, 500m² = 125 cells, safely above single-pixel artifacts.
    min_depression_area_sqm: float = 500.0

    # Minimum catchment area (hectares) draining to the depression's pour point.
    # A bowl's footprint can be small but drain a large upstream area (or vice versa);
    # both filters serve different physical purposes and must be kept separate.
    # Default 0.5 ha = 5000 m².
    min_catchment_area_ha: float = 0.5

    # Maximum number of ranked candidate locations returned by the API.
    max_candidates: int = 10

    # ── Output ────────────────────────────────────────────────────────────────
    # Shapely simplify tolerance (metres) for catchment polygon sent to frontend.
    # Reduces vertex count for smoother map rendering.
    polygon_simplify_tolerance_m: float = 1.0

    # ── OSM API (Module 10 — Water Mask Update) ──────────────────────────────
    # Using the primary OSM API for reliability (XML format).
    osm_api_url: str = "https://api.openstreetmap.org/api/0.6/map"

    # Timeout per individual OSM HTTP request (seconds).
    osm_timeout_s: int = 15

    # Safety buffer added around all water polygons/buffers in metres.
    # Prevents pond candidates from being placed right on the water edge.
    water_buffer_margin_m: float = 5.0

    # Default half-widths (metres) for linear waterways that carry no width= tag.
    # Source: OSM tagging guidelines + common survey values for rural India.
    default_river_width_m: float = 15.0
    default_stream_width_m: float = 3.0
    default_canal_width_m: float = 8.0
    default_drain_width_m: float = 1.5

    # When True (default), streams, ditches, and drains also trigger a hard veto.
    # Set False in config to allow check-dam style candidates on minor waterways.
    veto_minor_waterways: bool = True

    # In-memory Overpass response cache TTL (seconds). Water features are
    # effectively static on the timescale of a planning run, so 24h is safe.
    water_cache_ttl_s: int = 86400  # 24 h


# Module-level singleton — import this everywhere instead of calling Settings().
settings = Settings()
