"""
Parse an Overpass API XML response into Shapely geometries, then reproject
and buffer them into the DEM's metric CRS for rasterization.

Two geometry families from OSM water tagging:

  Area features  — ``natural=water``, ``landuse=reservoir``, ``waterway=riverbank``
                   These come as closed ways (polygons). No buffering needed;
                   the polygon already represents the true water extent.

  Linear features — ``waterway=river|stream|canal|drain|ditch``
                    These come as open ways (LineStrings). They need to be
                    buffered by (half the waterway width + safety margin) to
                    create an exclusion polygon.

Built-up land extraction (for land suitability):

  Area features  — ``building=*``, ``landuse=residential|commercial|industrial|
                    construction|cemetery``
                    These are polygon ways. They are returned as-is (no buffering
                    at parse time — caller applies builtup_buffer_margin_m).
"""

import logging
import xml.etree.ElementTree as ET

import pyproj
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import transform

_log = logging.getLogger(__name__)

# Maps OSM waterway= tag → Settings attribute name for the default half-width.
_WATERWAY_WIDTH_ATTR: dict[str, str] = {
    "river": "default_river_width_m",
    "stream": "default_stream_width_m",
    "canal": "default_canal_width_m",
    "drain": "default_drain_width_m",
    "ditch": "default_drain_width_m",
    "riverbank": "default_river_width_m",  # deprecated tag, treat as river
}

# Waterway types considered "minor" (subject to veto_minor_waterways flag).
_MINOR_WATERWAY_TYPES = {"stream", "drain", "ditch"}


def build_water_geometries(
    osm_xml: str,
    settings,
) -> list[tuple[Polygon | LineString, str]]:
    """
    Extract raw WGS84 Shapely geometries from an OSM API XML response.

    Returns:
        List of ``(geometry, tag_label)`` pairs where tag_label is a string
        like ``"lake"``, ``"reservoir"``, or ``"waterway:river"`` that
        identifies the water type for width-lookup later.
    """
    results: list[tuple[Polygon | LineString, str]] = []

    try:
        root = ET.fromstring(osm_xml)
    except ET.ParseError as exc:
        _log.error("Failed to parse OSM XML: %s", exc)
        return results

    # 1. Build node dictionary: id -> (lon, lat)
    nodes = {}
    for node in root.findall("node"):
        try:
            nodes[node.attrib["id"]] = (
                float(node.attrib["lon"]),
                float(node.attrib["lat"]),
            )
        except (KeyError, ValueError):
            continue

    # 2. Iterate ways and build geometries
    for way in root.findall("way"):
        tags = {
            tag.attrib["k"]: tag.attrib["v"]
            for tag in way.findall("tag")
            if "k" in tag.attrib and "v" in tag.attrib
        }

        # Collect coordinates for this way
        coords = []
        for nd in way.findall("nd"):
            ref = nd.attrib.get("ref")
            if ref in nodes:
                coords.append(nodes[ref])

        if len(coords) < 2:
            continue

        # ── Area water features (polygons) ─────────────────────────────────
        if (
            tags.get("natural") == "water"
            or tags.get("waterway") == "riverbank"
            or tags.get("landuse") == "reservoir"
        ):
            if len(coords) >= 3:
                # Ensure the ring is closed
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                poly = Polygon(coords)
                if poly.is_valid and not poly.is_empty:
                    label = tags.get("water", "area")
                    results.append((poly, label))
            continue

        # ── Linear waterway features (need buffering) ─────────────────────
        waterway_type = tags.get("waterway")
        if waterway_type not in _WATERWAY_WIDTH_ATTR:
            continue

        # Respect the veto_minor_waterways toggle
        if not settings.veto_minor_waterways and waterway_type in _MINOR_WATERWAY_TYPES:
            continue

        line = LineString(coords)
        if line.is_valid and not line.is_empty:
            results.append((line, f"waterway:{waterway_type}"))

    _log.debug(
        "Extracted %d water geometries from OSM XML",
        len(results),
    )
    return results


# ---------------------------------------------------------------------------
# Built-up land extraction (for land suitability exclusion — Module 1)
# ---------------------------------------------------------------------------

# Tags whose closed-way (polygon) forms mark non-excavatable built-up land.
# Values are matched as follows:
#   ("building", None) — match ANY non-empty value (house, yes, school, ...)
#   ("landuse", "residential") — match the exact value
_BUILTUP_POLYGON_TAGS: list[tuple[str, str | None]] = [
    ("building", None),  # any building footprint polygon
    ("landuse", "residential"),
    ("landuse", "commercial"),
    ("landuse", "industrial"),
    ("landuse", "construction"),
    ("landuse", "cemetery"),  # culturally incompatible in rural India
]


def build_builtup_geometries(osm_xml: str) -> list[Polygon]:
    """
    Extract WGS84 Shapely polygons for built-up / non-excavatable land.

    Parses the **same OSM XML blob** already fetched for water features —
    no additional HTTP call is made. The function is deliberately independent
    of ``build_water_geometries``; it can be called even if that function
    returned no results.

    OSM tags matched (polygon closed ways only):
      - ``building=*``           (any non-empty value)
      - ``landuse=residential``
      - ``landuse=commercial``
      - ``landuse=industrial``
      - ``landuse=construction``
      - ``landuse=cemetery``

    Linear ways with the above tags are ignored (rare and non-meaningful for
    footprint exclusion purposes).

    Args:
        osm_xml: Raw OSM API XML string (``<osm version="0.6">...</osm>``).

    Returns:
        List of WGS84 :class:`~shapely.geometry.Polygon` objects.
        Returns an empty list on XML parse error or when no matching features
        exist in the bounding box (fail-open: no exclusion applied).
    """
    results: list[Polygon] = []

    try:
        root = ET.fromstring(osm_xml)
    except ET.ParseError as exc:
        _log.error("Failed to parse OSM XML for built-up geometries: %s", exc)
        return results

    # 1. Build node dictionary: id -> (lon, lat)
    nodes: dict[str, tuple[float, float]] = {}
    for node in root.findall("node"):
        try:
            nodes[node.attrib["id"]] = (
                float(node.attrib["lon"]),
                float(node.attrib["lat"]),
            )
        except (KeyError, ValueError):
            continue

    # 2. Iterate ways and extract built-up polygon features
    for way in root.findall("way"):
        tags = {
            tag.attrib["k"]: tag.attrib["v"]
            for tag in way.findall("tag")
            if "k" in tag.attrib and "v" in tag.attrib
        }

        # Check if this way matches any built-up exclusion tag
        matched = False
        for osm_key, osm_value in _BUILTUP_POLYGON_TAGS:
            tag_val = tags.get(osm_key)
            if tag_val is None:
                continue
            # osm_value is None → match any non-empty value (e.g., building=*)
            # but ignore explicit negations like "no" or "false"
            if osm_value is None:
                if tag_val.lower() not in ("no", "false"):
                    matched = True
                    break
            elif tag_val == osm_value:
                matched = True
                break

        if not matched:
            continue

        # Collect coordinates for this way
        coords = []
        for nd in way.findall("nd"):
            ref = nd.attrib.get("ref")
            if ref in nodes:
                coords.append(nodes[ref])

        # Need at least 3 distinct points to form a valid polygon
        if len(coords) < 3:
            continue

        # Ensure the ring is closed
        if coords[0] != coords[-1]:
            coords.append(coords[0])

        poly = Polygon(coords)
        if poly.is_valid and not poly.is_empty:
            results.append(poly)

    _log.debug(
        "Extracted %d built-up land polygons from OSM XML",
        len(results),
    )
    return results


def reproject_and_buffer(
    geometries: list[tuple[Polygon | LineString, str]],
    settings,
    to_crs_epsg: int,
) -> list[Polygon | MultiPolygon]:
    """
    Reproject WGS84 geometries to a metric CRS and buffer linear waterways.

    Area polygons get a small safety-margin buffer (``water_buffer_margin_m``).
    Linear waterways get a buffer of ``(half_width + water_buffer_margin_m)``.

    Args:
        geometries:    Output of :func:`build_water_geometries`.
        settings:      The global ``Settings`` instance.
        to_crs_epsg:   EPSG code of the target metric CRS (e.g. 32644 for UTM44N).

    Returns:
        List of metric-CRS Shapely polygon geometries ready for rasterization.
    """
    transformer = pyproj.Transformer.from_crs(
        "EPSG:4326", f"EPSG:{to_crs_epsg}", always_xy=True
    )

    def _project(x, y):
        return transformer.transform(x, y)

    buffered: list[Polygon | MultiPolygon] = []

    for geom, tag in geometries:
        geom_m = transform(_project, geom)

        if geom_m.geom_type == "LineString":
            # Determine half-width for this waterway type
            waterway_type = tag.split(":")[-1]
            width_attr = _WATERWAY_WIDTH_ATTR.get(
                waterway_type, "default_stream_width_m"
            )
            half_width = getattr(settings, width_attr) / 2.0
            buffer_dist = half_width + settings.water_buffer_margin_m
        else:
            # Area polygons: safety margin only
            buffer_dist = settings.water_buffer_margin_m

        geom_m = geom_m.buffer(buffer_dist)
        if not geom_m.is_empty:
            buffered.append(geom_m)

    return buffered
