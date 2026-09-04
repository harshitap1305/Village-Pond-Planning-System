"""
Schemas for OSM-derived exclusion masks.

WaterMaskResult wraps the boolean numpy mask produced from Overpass data
(or the flat-area fallback) plus provenance metadata that is surfaced in
the API response so callers always know which method produced the exclusion.

LandMaskResult wraps the built-up land exclusion mask (buildings, residential
and commercial landuse) parsed from the same Overpass XML blob.
"""

from typing import Any, Literal

from pydantic import BaseModel


class WaterMaskResult(BaseModel):
    """
    Result of the water exclusion mask computation.

    Attributes:
        mask:          Boolean numpy array, same (rows, cols) as the DEM.
                       True = cell is inside a mapped (or probable) water body.
        source:        How the mask was produced:
                         "osm"                 — live Overpass API data
                         "flat_area_heuristic" — OSM unavailable; large flat
                                                 regions flagged as probable water
                         "unavailable"         — OSM failed AND heuristic
                                                 returned empty mask (no-op).
        feature_count: Number of OSM water features returned by Overpass
                       (0 for non-OSM sources).
        attribution:   Required ODbL credit string to surface in the frontend
                       wherever OSM-derived data is displayed.
    """

    mask: Any  # np.ndarray — arbitrary_types_allowed below
    source: Literal["osm", "flat_area_heuristic", "unavailable"]
    feature_count: int
    attribution: str = "© OpenStreetMap contributors"

    model_config = {"arbitrary_types_allowed": True}


class LandMaskResult(BaseModel):
    """
    Result of the OSM built-up land exclusion mask computation.

    Parsed from the same OSM XML blob already fetched for water features —
    no additional HTTP call is made.

    Attributes:
        mask:          Boolean numpy array, same (rows, cols) as the DEM.
                       True = cell overlaps a mapped building footprint or a
                       residential / commercial / industrial / construction /
                       cemetery landuse area.
        source:        How the mask was produced:
                         "osm"         — live OSM data parsed successfully
                         "unavailable" — OSM data absent or parse failed;
                                         mask is all-False (fail-open).
        feature_count: Number of distinct OSM built-up polygon features found
                       (0 when source is not "osm" or no features in bbox).
        attribution:   Required ODbL credit string to surface in the frontend.
    """

    mask: Any  # np.ndarray — arbitrary_types_allowed below
    source: Literal["osm", "unavailable"]
    feature_count: int
    attribution: str = "© OpenStreetMap contributors"

    model_config = {"arbitrary_types_allowed": True}
