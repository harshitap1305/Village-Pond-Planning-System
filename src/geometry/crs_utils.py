"""
Coordinate Reference System utilities.

detect_utm_epsg() auto-selects the right UTM zone for any lon/lat input,
so the system generalizes to contour files from any region of the world.
It is intentionally a pure function (no side-effects, no I/O) so it can
be exhaustively unit-tested without any external resources.
"""


def detect_utm_epsg(lon: float, lat: float) -> int:
    """
    Compute the EPSG code for the UTM zone that covers the given point.

    UTM divides the world into 60 six-degree-wide zones numbered 1-60
    from West to East starting at 180°W. Each zone has a northern and
    southern variant:
        Northern hemisphere (lat >= 0):  EPSG 32600 + zone  (e.g. zone 44 -> 32644)
        Southern hemisphere (lat < 0):   EPSG 32700 + zone  (e.g. zone 44 -> 32744)

    Args:
        lon: Longitude in decimal degrees, range [-180, 180].
        lat: Latitude in decimal degrees, range [-90, 90].

    Returns:
        EPSG code as an integer (e.g. 32644 for UTM 44N).

    Examples:
        >>> detect_utm_epsg(81.28, 21.26)   # Chhattisgarh, India
        32644
        >>> detect_utm_epsg(-74.0, 40.7)    # New York City
        32618
        >>> detect_utm_epsg(151.2, -33.9)   # Sydney, Australia
        32756
    """
    zone = int((lon + 180) / 6) + 1
    if lat >= 0:
        return 32600 + zone
    else:
        return 32700 + zone
