"""
KML/KMZ terrain source implementation.

Parses contour lines from Google Earth KML/KMZ files as exported by
ContourMapGenerator or similar tools.

Verified against: tests/fixtures/contours_1m.kml
────────────────────────────────────────────────
  Placemarks  : 2712
  Elevations  : 267.0 – 298.0 m  (+ 1.0 outlier label — passed through)
  Coord format: 2D only  lon,lat  (NO Z component in coordinates)
  Elev source : <name> tag  e.g. "277.0"  — NOT the coordinate Z value
  Namespace   : http://www.opengis.net/kml/2.2
  Nesting     : Folder > Folder > Folder > Placemark

Key parsing decisions:
  - Use lxml.etree directly (not fastkml) for full namespace control
  - Clark notation  {ns}tag  for all element lookups
  - Non-numeric <name> values are silently skipped (they're labels/style names)
  - Z value in coordinates is ignored — elevation always comes from <name>
  - Filtering bad elevations (e.g. the 1.0 outlier) is Module 3's job
"""

import zipfile
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Union

from lxml import etree

from src.schemas.terrain import ContourLine
from src.terrain.base import TerrainSource

# ── Namespace constants ────────────────────────────────────────────────────────

KML_NS = "http://www.opengis.net/kml/2.2"

# Clark notation helpers — avoids repeating f"{{{KML_NS}}}tag" everywhere
_PLACEMARK = f"{{{KML_NS}}}Placemark"
_NAME = f"{{{KML_NS}}}name"
_LINESTRING = f"{{{KML_NS}}}LineString"
_COORDINATES = f"{{{KML_NS}}}coordinates"


class KMLTerrainSource(TerrainSource):
    """
    Reads contour lines from a .kml or .kmz file.

    Usage — from a file path (scripts, tests):
        source = KMLTerrainSource.from_file("tests/fixtures/contours_1m.kml")
        contours = source.extract_contours()

    Usage — from raw bytes (API file upload, Module 12):
        source = KMLTerrainSource(file_bytes, filename="upload.kml")
        contours = source.extract_contours()
    """

    def __init__(self, data: bytes, filename: str = "input.kml") -> None:
        """
        Args:
            data:     Raw bytes of the KML or KMZ file.
            filename: Original filename — used only to detect .kmz extension.
                      Not used for anything security-sensitive.
        """
        self._filename = filename.lower()
        # Resolve immediately so KMZ errors surface at construction time
        self._kml_bytes: bytes = self._resolve_kml_bytes(data)

    # ── Alternative constructor ───────────────────────────────────────────────

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "KMLTerrainSource":
        """
        Convenience constructor for local file paths.
        Used in scripts and tests; the API layer passes raw bytes instead.
        """
        path = Path(path)
        return cls(path.read_bytes(), filename=path.name)

    # ── KMZ support ───────────────────────────────────────────────────────────

    def _resolve_kml_bytes(self, data: bytes) -> bytes:
        """Return plain KML bytes, unzipping from KMZ if necessary."""
        if self._filename.endswith(".kmz"):
            return self._extract_kml_from_kmz(data)
        return data

    @staticmethod
    def _extract_kml_from_kmz(data: bytes) -> bytes:
        """
        Unzip a KMZ archive in memory and return the main KML document.

        KMZ is a ZIP file. The main document is conventionally named 'doc.kml'.
        If that name isn't present, we fall back to the first .kml entry found.
        """
        try:
            with zipfile.ZipFile(BytesIO(data)) as zf:
                kml_names = [
                    name for name in zf.namelist() if name.lower().endswith(".kml")
                ]
                if not kml_names:
                    raise ValueError("KMZ archive contains no .kml files")

                # Standard convention: prefer doc.kml
                target = "doc.kml" if "doc.kml" in kml_names else kml_names[0]
                return zf.read(target)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"KMZ file is not a valid ZIP archive: {exc}") from exc

    # ── Main parsing ──────────────────────────────────────────────────────────

    def extract_contours(self) -> List[ContourLine]:
        """
        Parse all Placemarks from the KML and return ContourLine objects.

        Algorithm:
          1. Parse XML with lxml (handles py:pytype namespace attrs cleanly)
          2. Iterate every <Placemark> in the document tree (any nesting depth)
          3. Per Placemark: read elevation from <name>, coordinates from <LineString>
          4. Skip Placemarks that aren't valid contour lines (no LineString,
             non-numeric name, fewer than 2 points)

        Note: This method returns ALL parseable contours including any elevation
        outliers. Semantic validation (min count, elevation range, etc.) is
        intentionally deferred to Module 3's validate_contours() function.
        """
        try:
            root = etree.fromstring(self._kml_bytes)
        except etree.XMLSyntaxError as exc:
            raise ValueError(f"Invalid XML in KML file: {exc}") from exc

        contours: List[ContourLine] = []

        # iter() walks the entire subtree regardless of nesting depth.
        # Our file: Folder > Folder > Folder > Placemark — iter handles all depths.
        for placemark in root.iter(_PLACEMARK):
            contour = self._parse_placemark(placemark)
            if contour is not None:
                contours.append(contour)

        return contours

    # ── Per-element helpers ───────────────────────────────────────────────────

    def _parse_placemark(self, placemark: etree._Element) -> Optional[ContourLine]:
        """
        Extract one ContourLine from a <Placemark> element.
        Returns None for any Placemark that isn't a valid contour line.
        """
        # Step 1: elevation from <name>
        elevation = self._read_elevation(placemark)
        if elevation is None:
            return None  # Label/style Placemark — no numeric elevation

        # Step 2: coordinates from <LineString><coordinates>
        coords_elem = placemark.find(f".//{_COORDINATES}")
        if coords_elem is None or not coords_elem.text:
            return None  # Point or Polygon Placemark — not a line

        # Step 3: parse the coordinate text
        points = self._parse_coordinates(coords_elem.text)
        if len(points) < 2:
            return None  # Degenerate geometry — single point

        # Step 4: construct via Pydantic (validators run here)
        try:
            return ContourLine(elevation=elevation, points=points)
        except ValueError:
            return None  # Pydantic validator rejected it (shouldn't happen given checks above)

    def _read_elevation(self, placemark: etree._Element) -> Optional[float]:
        """
        Read the elevation value from the <name> child of a Placemark.

        In contours_1m.kml every terrain Placemark has:
            <name xmlns:py="..." py:pytype="str">277.0</name>

        The py:pytype namespace attribute doesn't affect .text — lxml returns
        the string content directly, so we just strip and cast to float.

        Non-terrain Placemarks (e.g. the containing Folder name "lines") will
        have text like "ContourMapGenerator" or "lines" — float() will raise
        ValueError, which we catch and return None.
        """
        name_elem = placemark.find(_NAME)
        if name_elem is None or not name_elem.text:
            return None

        try:
            return float(name_elem.text.strip())
        except ValueError:
            return None  # Text content is not a number — skip this Placemark

    @staticmethod
    def _parse_coordinates(coords_text: str) -> List[tuple]:
        """
        Parse KML <coordinates> text into (lon, lat) tuples.

        KML coordinate formats handled:
          2D:  "lon,lat lon,lat ..."           ← our file
          3D:  "lon,lat,alt lon,lat,alt ..."   ← other exporters; alt is ignored

        Whitespace (spaces, newlines, tabs) separates tuples.
        Commas separate lon/lat(/alt) within each tuple.

        Bad tokens are skipped silently rather than crashing the whole parse.
        """
        points = []

        for token in coords_text.split():
            token = token.strip()
            if not token:
                continue

            parts = token.split(",")
            if len(parts) < 2:
                continue  # Malformed token — skip

            try:
                lon = float(parts[0])
                lat = float(parts[1])
                # parts[2] would be Z/altitude — ignored because elevation
                # comes from the Placemark's <name> tag in this file format
                points.append((lon, lat))
            except (ValueError, IndexError):
                continue  # Non-numeric coordinate — skip token

        return points
