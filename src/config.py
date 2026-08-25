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

    # ── File Upload Limits ────────────────────────────────────────────────────
    max_upload_mb: int = 20
    allowed_extensions: list[str] = [".kml", ".kmz"]

    # ── DEM Construction (Module 5) ───────────────────────────────────────────
    # Grid cell size in metres. Smaller = finer terrain model, slower to build.
    cell_size_m: float = 2.0
    # Extra padding around the bounding box so edge contour points aren't clipped.
    dem_buffer_cells: int = 2

    # ── Hydrological Analysis (Modules 7–9) ──────────────────────────────────
    # Only cells above this flow-accumulation percentile are pond candidates.
    accumulation_percentile_threshold: float = 90.0
    # Steeper sites than this (degrees) are excluded from candidates.
    max_candidate_slope_deg: float = 15.0
    # Maximum number of ranked candidate locations returned by the API.
    max_candidates: int = 10

    # ── Output ────────────────────────────────────────────────────────────────
    # Shapely simplify tolerance (metres) for catchment polygon sent to frontend.
    # Reduces vertex count for smoother map rendering.
    polygon_simplify_tolerance_m: float = 1.0


# Module-level singleton — import this everywhere instead of calling Settings().
settings = Settings()
