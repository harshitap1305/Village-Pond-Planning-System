"""
Abstract base for all terrain data sources.

Design: Strategy pattern
────────────────────────
Today:   KMLTerrainSource   (Module 2)
Future:  GeoTIFFTerrainSource, SHPTerrainSource

All downstream code — DEM builder, flow engine, catchment delineator —
depends ONLY on this single-method interface. Swapping the input format
requires zero changes outside the src/terrain/ package.
"""

from abc import ABC, abstractmethod
from typing import List

from src.schemas.terrain import ContourLine


class TerrainSource(ABC):
    """
    Contract: given some terrain data (file, URL, bytes, etc.),
    return a list of ContourLine objects in WGS84 coordinates.

    Implementors must:
    - Accept their input in __init__
    - Expose exactly this one method
    - Raise ValueError (or a subclass) on parse failure

    Single-method interfaces are trivial to mock in tests:
        class FakeTerrainSource(TerrainSource):
            def extract_contours(self): return [ContourLine(...)]
    """

    @abstractmethod
    def extract_contours(self) -> List[ContourLine]:
        """
        Parse the underlying terrain data and return contour lines.

        Returns:
            List of ContourLine objects, one per elevation contour.
            Order is not guaranteed — callers must not assume sorted output.

        Raises:
            ValueError: if the source data cannot be parsed (Module 3
                        wraps this in TerrainParseError for the API layer).
        """
        ...
