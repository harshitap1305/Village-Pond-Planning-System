"""
Schemas for catchment delineation and pond candidate locations.
"""

from pydantic import BaseModel


class CandidatePoint(BaseModel):
    """
    A single candidate location for excavating a village pond.

    Attributes:
        lat: WGS84 latitude of the representative point.
        lon: WGS84 longitude of the representative point.
        elevation: Terrain elevation in metres at this point.
        score: Normalized score from 0.0 (worst) to 1.0 (best) based on flow accumulation.
    """

    lat: float
    lon: float
    elevation: float
    score: float


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
