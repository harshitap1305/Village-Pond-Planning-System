"""
Input validation for terrain data ingestion — two distinct layers.

Layer 1 — validate_file():
    File-level guard run BEFORE parsing. Checks extension and byte size.
    Fast-fail: don't read 200 MB of garbage into memory to discover it's a .csv.

Layer 2 — validate_contours():
    Semantic validation run AFTER parsing. Checks that the parsed contours
    can actually support DEM interpolation and hydrological analysis.

Both functions are pure (no I/O, no side effects) and fully unit-testable
without instantiating KMLTerrainSource or spinning up FastAPI.

All thresholds come from settings — no hard-coded magic numbers.
"""

from pathlib import Path
from typing import List

from src.config import settings
from src.schemas.terrain import ContourLine
from src.terrain.exceptions import (
    FileTooLargeError,
    InvalidGeometryError,
    UnsupportedFormatError,
)


def validate_file(filename: str, size_bytes: int) -> None:
    """
    File-level guard — run BEFORE parsing.

    Args:
        filename:   Original filename (used only for extension check).
        size_bytes: File size in bytes.

    Raises:
        UnsupportedFormatError: Extension not in settings.allowed_extensions.
        FileTooLargeError:      Size exceeds settings.max_upload_mb.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in settings.allowed_extensions:
        raise UnsupportedFormatError(
            f"Unsupported file type '{suffix}'. "
            f"Accepted formats: {', '.join(settings.allowed_extensions)}"
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    if size_bytes > max_bytes:
        size_mb = size_bytes / (1024 * 1024)
        raise FileTooLargeError(
            f"File is {size_mb:.1f} MB, which exceeds the "
            f"{settings.max_upload_mb} MB upload limit."
        )


def validate_contours(contours: List[ContourLine]) -> None:
    """
    Semantic validation — run AFTER parsing.

    Checks that the contours are geometrically sound for DEM interpolation.
    Does NOT check geographic bounds (India lat/lon range) — not the parser's job.
    Does NOT filter outlier elevations — filtering is a separate concern.

    Args:
        contours: List of ContourLine objects returned by TerrainSource.

    Raises:
        InvalidGeometryError: Any of the checks below fail.

    Checks:
        1. At least 2 contour lines — need multiple elevation levels to
           interpolate a surface. One line gives you a cliff, not a terrain.
        2. At least 2 unique elevation values — all-same elevation means a flat
           plane; there's no slope, no flow direction, no pond site to find.
        3. Non-zero spatial extent — bounding box must span real geographic area.
           A near-zero box means all contours cluster at one point, which
           is either a data error or a single-point marker file.
    """
    # ── Check 1: Minimum contour count ───────────────────────────────────────
    if len(contours) < 2:
        raise InvalidGeometryError(
            f"At least 2 contour lines are required to interpolate a DEM surface, "
            f"got {len(contours)}."
        )

    # ── Check 2: Elevation variety ────────────────────────────────────────────
    unique_elevations = {c.elevation for c in contours}
    if len(unique_elevations) < 2:
        elev = next(iter(unique_elevations))
        raise InvalidGeometryError(
            f"All {len(contours)} contour line(s) share the same elevation "
            f"({elev} m). Cannot compute slope or flow direction from a flat surface."
        )

    # ── Check 3: Non-zero spatial extent ─────────────────────────────────────
    all_lons = [lon for c in contours for lon, _ in c.points]
    all_lats = [lat for c in contours for _, lat in c.points]

    lon_range = max(all_lons) - min(all_lons)
    lat_range = max(all_lats) - min(all_lats)

    # 0.0001 degrees ≈ 11 metres at equator — anything smaller is degenerate
    _MIN_DEGREE_SPAN = 0.0001
    if lon_range < _MIN_DEGREE_SPAN or lat_range < _MIN_DEGREE_SPAN:
        raise InvalidGeometryError(
            f"Near-zero spatial extent "
            f"(lon_range={lon_range:.6f}°, lat_range={lat_range:.6f}°). "
            f"Bounding box is too small to build a meaningful terrain model."
        )
