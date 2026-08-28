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
