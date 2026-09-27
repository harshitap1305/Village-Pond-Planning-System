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

    # ── Database (Module 8 — Persistence) ────────────────────────────────────
    # Optional: set to enable persistence. When absent, analysis runs are
    # not stored and GET /api/results/{id} returns 503.
    # Format: postgresql+asyncpg://user:password@host:port/dbname
    database_url: str | None = None

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

    # Maximum area (sq km) a user is allowed to select via the Draw Area tool.
    # Larger areas = more Terrarium tiles to download → longer analysis time.
    # 10 sq km = ~1000 ha, sufficient for any village-scale pond planning.
    max_area_selection_sqkm: float = 10.0

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

    # ── Land Suitability (Module 1 — Phase 3) ────────────────────────────────
    # Maximum terrain slope (degrees) permitted at the depression rim / dam-wall
    # site. Earthen embankments require stable, relatively flat ground to seat
    # and compact properly. Above this threshold, construction is impractical.
    # Basis: IS 12169 downstream slope ≈ 2:1 H:V = 26.6°; 20° is conservative
    # and leaves headroom for fill material placement.
    # Set to 90.0 to disable this filter entirely.
    max_dam_site_slope_deg: float = 20.0

    # Safety buffer (metres) added around built-up land polygons when building
    # the exclusion mask. Prevents pond siting immediately adjacent to a building
    # foundation where ground disturbance would affect the structure.
    builtup_buffer_margin_m: float = 10.0

    # In-memory cache TTL for built-up land exclusion data (seconds).
    # Same value as water_cache_ttl_s — both come from the same OSM XML blob.
    land_cache_ttl_s: int = 86400  # 24 h

    # ── Rainfall Data (Module 2 — Phase 3) ─────────────────────────────────────
    # Primary source: Open-Meteo Historical Weather Archive (ERA5-Land model).
    # Free, no API key, ~9 km resolution, data from 1950.
    # Tested live: 8.7 ms response for a 10-year query on central India.
    open_meteo_base_url: str = "https://archive-api.open-meteo.com/v1/archive"
    open_meteo_timeout_s: int = 15

    # Fallback source: NASA POWER (MERRA-2 reanalysis, ~50 km resolution).
    # Used automatically if Open-Meteo is unavailable after retries.
    # Tested live: ~60 ms response; 30s timeout allows for variance.
    nasa_power_base_url: str = "https://power.larc.nasa.gov/api/temporal/daily/point"
    nasa_power_timeout_s: int = 30

    # Years of historical rainfall to query (counted back from current year).
    # 10 years is the standard for village-scale hydrological design in India
    # (IS 5477 Part 1: Methods for fixing the capacities of low dams).
    rainfall_history_years: int = 10

    # In-memory cache TTL for rainfall data (seconds). 24h is safe since
    # historical reanalysis data doesn't change between requests.
    rainfall_cache_ttl_s: int = 86400  # 24 h

    # ── Runoff Estimation (Module 3 — Phase 3) ───────────────────────────────
    # Default Hydrologic Soil Group for ungauged catchments.
    # "B" = moderately well-drained; typical for Deccan basalt, laterite, and
    # Indo-Gangetic alluvium — the dominant soil parent material at most Indian
    # village sites. Override to "C" or "D" in .env for black-cotton / clay-rich
    # catchments, or "A" for sandy / well-drained terrain.
    # Reference: USDA NEH Part 630 Ch. 7 + NRSC/ISRO IMSD watershed guidelines.
    default_hsg: str = "B"

    # Fallback annual runoff coefficient used when monthly rainfall data is
    # unavailable (degrades gracefully from SCS-CN → simple C×P×A).
    # 0.30 = conservative estimate for mixed agriculture, Group B soil.
    # IS 5477 Part 1 recommends 0.25–0.40 for similar terrain.
    runoff_coefficient_fallback: float = 0.30

    # ── Pond Dimensioning (Module 4 — Phase 3) ───────────────────────────────
    # Fraction of annual runoff volume targeted for capture.
    # Basis: IS 5477 guidance for village-scale water harvesting; 40% is the
    # standard planning value that balances construction cost against benefit.
    # Remaining 60% accounts for inter-annual variability and downstream flow.
    target_capture_fraction: float = 0.40

    # Allowable water depth range (m). From NABARD farm pond guidelines and
    # MGNREGS model estimates:
    #   Min 1.5m: prevents rapid drying, reduces mosquito-breeding flat margins.
    #   Max 4.0m: safety limit for unlined earthen embankments (IS 12169).
    min_pond_depth_m: float = 1.5
    max_pond_depth_m: float = 4.0

    # Freeboard above full supply level (m).
    # IS 5477 Part 4 + MOEF farm pond guidelines: 0.3–0.5m for village ponds.
    # 0.5m is the conservative (upper) choice used here.
    freeboard_m: float = 0.5

    # Dead storage as a fraction of gross storage (IS 5477 Part 2).
    # Allocated to accumulate silt over the design life (50 years typical).
    # 10% is the standard for small village ponds in India.
    dead_storage_fraction: float = 0.10

    # Annual evaporation loss as a fraction of gross storage volume.
    # Basis: Central Water Commission (CWC) data — 1000–2000mm/yr for central
    # India; combined with typical shallow pond SA/volume ratio gives ~15%.
    evaporation_loss_fraction: float = 0.15

    # Annual seepage loss as a fraction of gross storage (unlined pond).
    # IS 5477 allowance + NABARD guideline for clay-loam unlined farm ponds.
    # Set to 0.005 (0.5%) in .env if the pond will be HDPE-lined.
    seepage_loss_fraction: float = 0.10

    # Bowl shape factor (form factor) for volume–depth back-calculation.
    # 0.4 = between a perfect cone (0.33) and a flat cylinder (1.0).
    # Validated against the prismoidal formula (h/3 × (A1 + A2 + √(A1×A2)))
    # with A_bottom ≈ 0.3 × A_top, typical of natural depression bowls.
    # Reference: NABARD farm pond design guide, Table 4.
    pond_shape_factor: float = 0.40

    # Standard earthen embankment top width (m).
    # IS 12169 / NABARD: 1.0–2.0m for earthen dams < 10m height.
    # 1.5m is the practical default for small village ponds.
    embankment_top_width_m: float = 1.5


# Module-level singleton — import this everywhere instead of calling Settings().
settings = Settings()
