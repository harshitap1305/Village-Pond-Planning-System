# Village Pond Planning System

AI-assisted web tool for identifying optimal rainwater harvesting pond locations in rural villages.

## Overview

Accepts KML/KMZ contour data for a village area and returns:
- **Ranked candidate pond locations** (lat/lon + score)
- **Estimated catchment polygon** (GeoJSON)
- **Runoff volume estimate** based on historical rainfall
- **Recommended pond depth and storage capacity**

Built for the CSD Assignment — AI-based Village Pond Planning System.

## How it Works (Algorithm & Logic)

The system automates the highly manual civil engineering process of topographical surveying and hydrological analysis. The pipeline runs completely offline (except for an OSM exclusion check) in about 60 seconds:

1. **Data Parsing & Coordinate Projection**
   - Extracts vector contour lines from the uploaded KML/KMZ files.
   - Automatically determines the correct UTM Zone and reprojects WGS84 (Lat/Lon) coordinates into a local metric Coordinate Reference System (CRS). This ensures all subsequent calculations (area, volume) are accurately measured in meters.
   - Densifies the vector lines to generate a dense 3D point cloud.

2. **DEM Generation (Interpolation)**
   - Uses Inverse Distance Weighting (IDW) to interpolate the sparse point cloud into a continuous 2D raster grid (Digital Elevation Model).

3. **Hydrological Conditioning**
   - Raw DEMs contain artificial "pits" or sinks that trap simulated water. The system uses a **Priority-Flood algorithm** to fill these depressions, creating a hydrologically conditioned DEM where water flows continuously toward the map edges.

4. **Flow Direction & Accumulation (D8 Algorithm)**
   - Computes the steepest downhill slope for every cell to determine flow direction (`pysheds`).
   - Calculates the upstream Flow Accumulation for every cell (how many cells flow into it). High accumulation pathways represent natural streams and valleys.

5. **Existing Water Exclusion (OpenStreetMap)**
   - Queries the main OpenStreetMap (OSM) API to download existing mapped rivers, streams, canals, and lakes as XML.
   - Converts the XML nodes/ways into buffered Shapely polygons, rasterizes them, and builds a strict boolean exclusion mask to prevent building a pond on top of an existing river.
   - Uses a fallback "flat-area heuristic" to exclude massive flat plains if the OSM network is down.

6. **Candidate Scoring & Selection**
   - Subtracts the conditioned DEM from the raw DEM to identify natural topographic depressions ("bowls").
   - Calculates the exact water storage volume ($m^3$), depression area, and depth for every bowl.
   - Ranks the candidates based on a weighted formula prioritizing large catchments, deep bowls, and high flow accumulation. Vetoes any candidate touching the OSM exclusion mask.

7. **Watershed Delineation**
   - Takes the #1 ranked pond location (the "pour point") and performs an upstream Breadth-First Search (BFS) on the flow direction grid.
   - Converts the resulting raster mask into a smoothed GeoJSON polygon representing the exact catchment area.

## Technology Stack

- **Backend**: Python 3.12 · FastAPI · uvicorn
- **Geospatial**: NumPy · SciPy · PyProj · Rasterio · Shapely · pysheds
- **KML Parsing**: lxml · fastkml
- **Config**: pydantic-settings (12-factor env-based)

## Quick Start

### Prerequisites
- Python 3.12
- `build-essential` and `libgdal-dev` (required for geospatial libraries)
  ```bash
  sudo apt-get install build-essential libgdal-dev
  ```

### Setup

```bash
# Clone the repo
git clone git@github.com:harshitap1305/Village-Pond-Planning-System.git
cd Village-Pond-Planning-System

# Create and activate virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment config
cp .env.example .env
```

### Run the API (Locally)

```bash
uvicorn src.api.main:app --reload
# Interactive API docs: http://localhost:8000/docs
```

### Run the API (Docker)

```bash
docker compose up --build
# Interactive API docs: http://localhost:8000/docs
```

### Run Tests

```bash
# Run fast unit tests only
pytest -m "not integration"

# Run all tests (including slow pipeline tests)
pytest

# With coverage:
pytest --cov=src --cov-report=term-missing
```

## API Usage

```bash
# Example curl request to analyze a KML file
curl -F "file=@tests/fixtures/contours_1m.kml" http://localhost:8000/analyzeContour
```

## Project Structure

```
src/
├── config.py           # Central config (pydantic-settings)
├── terrain/            # KML/KMZ parsing, TerrainSource interface
├── geometry/           # Point cloud extraction, CRS reprojection
├── dem/                # DEM interpolation, sink-filling, slope
├── hydrology/          # D8 flow direction, accumulation, watershed
├── catchment/          # Candidate selection, catchment metrics
├── api/                # FastAPI routes and error handlers
└── schemas/            # Pydantic models (shared across modules)
tests/
├── fixtures/           # contours_1m.kml, toy DEMs, broken KMLs
├── unit/               # Per-module unit tests
└── integration/        # Full pipeline & API-level tests
docs/
└── architecture.md     # System design and module map
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full system design.
See [docs/submission_report.md](docs/submission_report.md) for the detailed project report.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/analyzeContour` | Upload KML/KMZ, returns candidates + catchment |
| `GET`  | `/health` | Health check |
| `GET`  | `/docs` | Interactive Swagger UI |

## License

MIT
