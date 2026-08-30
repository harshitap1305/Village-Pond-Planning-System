import json
from pathlib import Path

import httpx
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt

from src.terrain.kml_source import KMLTerrainSource

# 1. Hit the local API
print("Sending KML to local API (this takes ~60s)...")
url = "http://localhost:8000/analyzeContour"
files = {
    "file": (
        "contours_1m.kml",
        open("tests/fixtures/contours_1m.kml", "rb"),
        "application/vnd.google-earth.kml+xml",
    )
}
response = httpx.post(url, files=files, timeout=120.0)
response.raise_for_status()
data = response.json()

# 2. Extract geometry and the selected pond location
polygon_geom = data["catchment"]["polygon_geojson"]
best_pond = data["selected_location"]

# 3. Create a GeoJSON FeatureCollection
feature_collection = {"type": "FeatureCollection", "features": []}

# --- NEW: Extract contours and color them by elevation ---
kml_bytes = Path("tests/fixtures/contours_1m.kml").read_bytes()
source = KMLTerrainSource(kml_bytes)
contours = source.extract_contours()

# Find min and max elevation to normalize colors
elevations = [c.elevation for c in contours]
min_elev, max_elev = min(elevations), max(elevations)
cmap = plt.get_cmap(
    "viridis"
)  # Viridis goes from dark purple (low) to green (mid) to yellow (high)
norm = mcolors.Normalize(vmin=min_elev, vmax=max_elev)

print(
    f"Adding {len(contours)} contour lines colored by elevation (Min: {min_elev}m, Max: {max_elev}m)..."
)
for c in contours:
    # Get hex color from colormap
    rgba = cmap(norm(c.elevation))
    hex_color = mcolors.to_hex(rgba)

    # Shapely coordinates are typically (lon, lat) or (lon, lat, z). GeoJSON expects [lon, lat]
    coords = [[x, y] for x, y in c.points]

    feature_collection["features"].append(
        {
            "type": "Feature",
            "properties": {
                "name": f"Contour {c.elevation}m",
                "elevation": c.elevation,
                "stroke": hex_color,
                "stroke-width": 2,
                "stroke-opacity": 0.8,
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        }
    )

# --- Add the catchment polygon ---
feature_collection["features"].append(
    {
        "type": "Feature",
        "properties": {
            "name": "Catchment Area",
            "area_ha": data["catchment"]["area_ha"],
            "fill": "#3388ff",
            "fill-opacity": 0.4,
        },
        "geometry": polygon_geom,
    }
)

# Add ALL candidate locations as markers
for i, candidate in enumerate(data["candidate_locations"]):
    is_best = i == 0
    color = "#ff0000" if is_best else "#ff8800"
    size = "large"
    symbol = "water" if is_best else "star"
    name = (
        f"Optimal Pond Location | Storage: {candidate.get('estimated_storage_m3', 0):.0f}m³ | Catchment: {candidate.get('catchment_area_ha', 0):.2f} ha | Score: {candidate['score']:.3f}"
        if is_best
        else f"Candidate #{i+1} | Storage: {candidate.get('estimated_storage_m3', 0):.0f}m³ | Catchment: {candidate.get('catchment_area_ha', 0):.2f} ha | Score: {candidate['score']:.3f}"
    )

    feature_collection["features"].append(
        {
            "type": "Feature",
            "properties": {
                "name": name,
                "elevation": candidate["elevation"],
                "score": candidate["score"],
                "catchment_area_ha": candidate.get("catchment_area_ha", 0),
                "marker-color": color,
                "marker-size": size,
                "marker-symbol": symbol,
            },
            "geometry": {
                "type": "Point",
                "coordinates": [candidate["lon"], candidate["lat"]],
            },
        }
    )

    # NEW: Add the catchment polygon if available (all should have it now)
    if candidate.get("catchment_polygon_geojson") and not is_best:
        feature_collection["features"].append(
            {
                "type": "Feature",
                "properties": {
                    "name": f"Catchment Area (Candidate #{i+1})",
                    "area_ha": candidate.get("catchment_area_ha", 0),
                    "fill": "#ff8800",
                    "fill-opacity": 0.2,
                    "stroke": "#ff8800",
                    "stroke-width": 1,
                },
                "geometry": candidate["catchment_polygon_geojson"],
            }
        )

# 4. Save to file
output_file = "demo_result.geojson"
with open(output_file, "w") as f:
    json.dump(feature_collection, f, indent=2)

print(f"\nSuccess! Saved to {output_file}")
print(
    "Drag and drop this file into https://geojson.io/ along with your KML to visualize."
)
