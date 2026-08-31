"""
Schemas for catchment delineation and pond candidate locations.
"""

from pydantic import BaseModel, Field


class CandidatePoint(BaseModel):
    """
    A single candidate location for excavating a village pond.

    Attributes:
        lat:                  WGS84 latitude of the pour point (rim saddle).
        lon:                  WGS84 longitude of the pour point (rim saddle).
        elevation:            Terrain elevation in metres at the pour point.
        score:                Normalized catchment score 0–1.
                              = sum(flow_accum_cond at tied sink cells) / DEM_cell_count.
                              Higher means more upstream water drains to this bowl.
        depression_depth_m:   Maximum fill depth inside the bowl (m).
        depression_area_ha:   Bowl footprint area in hectares.
        catchment_area_ha:    Uphill watershed area draining into this bowl (hectares).
        estimated_storage_m3: Topographic fill volume (m³) — an upper-bound estimate
                              of how much water the bowl can hold.
        had_flat_bottom:      True if the bowl's minimum elevation was a multi-cell
                              plateau (tied values). Informational only — the BFS
                              was seeded from all tied cells, so the delineated
                              polygon and catchment count are still correct.

    Internal field (excluded from API serialization):
        bowl_sink_rcs:        List of (row, col) tuples for the conditioned-DEM
                              sink cells used to seed the watershed BFS.
        on_or_near_mapped_water: True if the pour point falls inside or within
                              one DEM cell of the OSM water exclusion mask.
                              Informational only — candidates found by the
                              automatic search will never have this True (they
                              were vetoed). Exposed as a warning for cases where
                              the user manually overrides the pour point.
    """

    lat: float
    lon: float
    elevation: float
    score: float
    depression_depth_m: float
    depression_area_ha: float
    catchment_area_ha: float
    estimated_storage_m3: float
    had_flat_bottom: bool = False
    on_or_near_mapped_water: bool = False
    catchment_polygon_geojson: dict | None = Field(
        default=None, description="GeoJSON polygon of the catchment area"
    )

    # Internal routing field — stripped before API serialization via Field(exclude=True)
    bowl_sink_rcs: list[tuple[int, int]] = Field(default=[], exclude=True)


class CatchmentMetrics(BaseModel):
    """
    Statistical summary of the terrain within a delineated catchment.

    Attributes:
        area_ha:         Total catchment area in hectares.
        cell_count:      Number of DEM cells in the catchment.
        elevation_stats: Dict with keys 'min', 'max', 'mean' in metres.
        slope_stats:     Dict with keys 'min', 'max', 'mean' in degrees.
    """

    area_ha: float
    cell_count: int
    elevation_stats: dict[str, float]
    slope_stats: dict[str, float]
