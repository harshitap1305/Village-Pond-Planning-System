"""
Response schemas for the POST /analyzeContour endpoint.

These types define the exact JSON contract the API returns to the frontend.
Every field is typed and documented so FastAPI auto-generates accurate Swagger docs.
"""

from typing import Any, Dict, List

from pydantic import BaseModel

from src.schemas.catchment import CandidatePoint


class CatchmentResult(BaseModel):
    """
    The delineated catchment area and its terrain statistics.

    Attributes:
        area_ha:        Catchment area in hectares.
        polygon_geojson: GeoJSON geometry dict (Polygon or MultiPolygon in WGS84).
        elevation_stats: Dict with 'min', 'max', 'mean' in metres.
        slope_stats:    Dict with 'min', 'max', 'mean' in degrees.
    """

    area_ha: float
    polygon_geojson: Dict[str, Any]
    elevation_stats: Dict[str, float]
    slope_stats: Dict[str, float]


class AnalysisMetadata(BaseModel):
    """
    Provenance information about the analysis run.

    Attributes:
        dem_rows:       Number of rows in the DEM grid.
        dem_cols:       Number of columns in the DEM grid.
        dem_cell_size_m: Cell resolution in metres.
        crs_used:       EPSG code of the projected CRS used internally.
        contour_count:  Number of contour lines parsed from the input file.
    """

    dem_rows: int
    dem_cols: int
    dem_cell_size_m: float
    crs_used: str
    contour_count: int


class WaterExclusionMetadata(BaseModel):
    """
    Metadata about the OSM water exclusion layer used in this analysis.

    Attributes:
        source:                How the water mask was produced.
                               ``"osm"``                — live Overpass API data
                               ``"flat_area_heuristic"`` — OSM unavailable; large flat
                                                           regions used as fallback.
                               ``"unavailable"``         — mask was empty / all sources failed.
        excluded_feature_count: Number of distinct OSM water features fetched.
                                0 when source is not ``"osm"``.
        attribution:           Required ODbL credit string for OSM data.
                               Display this wherever the catchment map is shown.
    """

    source: str
    excluded_feature_count: int
    attribution: str


class AnalysisResult(BaseModel):
    """
    Top-level response for POST /analyzeContour.

    Attributes:
        candidate_locations: Ranked list of pond candidate points (best first).
        selected_location:   The top-ranked candidate used for watershed delineation.
        catchment:           Catchment polygon and terrain statistics.
        metadata:            Provenance information about the analysis run.
        water_exclusion:     Metadata about the OSM water exclusion layer applied.
    """

    candidate_locations: List[CandidatePoint]
    selected_location: CandidatePoint
    catchment: CatchmentResult
    metadata: AnalysisMetadata
    water_exclusion: WaterExclusionMetadata
