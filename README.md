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

1. **Data Extraction & Coordinate Graphing**
   - Parses the XML-based KML/KMZ files to extract contour elevation rings (LineStrings).
   - Determines the correct local UTM Zone and transforms all WGS84 (Lat/Lon) coordinates into a metric Coordinate Reference System (CRS).
   - Densifies the contour lines by adding vertices at regular 1-meter intervals, effectively building a dense 3D point cloud $(x, y, z)$.

2. **Raster Grid (DEM) Generation via IDW**
   - We divide the village area into a 2D matrix of discrete cells (e.g., $2m \times 2m$ spatial resolution).
   - We use an **Inverse Distance Weighting (IDW)** algorithm backed by a KD-Tree spatial index. For each empty cell in the grid, the algorithm finds the $k$-nearest contour points and assigns an elevation weighted by the inverse of their distance. This creates a continuous Digital Elevation Model (DEM).

3. **Hydrological Conditioning (Priority-Flood Algorithm)**
   - Natural, mathematically-interpolated DEMs contain artificial "pits" or sinks (cells surrounded by higher elevation cells) which trap simulated water flow.
   - We run a **Priority-Flood algorithm** that simulates raising the water level in these pits until they spill over, ensuring that every cell in the DEM has a continuous downhill path to the edge of the map.

4. **Flow Network Graphing (D8 Algorithm)**
   - The terrain is modeled as a directed mathematical graph. Using the **D8 (Deterministic Eight-Node) Algorithm** via `pysheds`, every cell calculates the steepest downhill slope among its 8 immediate neighbors.
   - Each cell points a directed edge to its steepest downhill neighbor, creating a network of flow pointers.
   - We traverse this graph to compute **Flow Accumulation**: the total number of upstream cells that drain into any given cell. High-accumulation pathways mathematically represent rivers and valleys.

5. **Existing Water Exclusion (OpenStreetMap)**
   - To prevent the system from proposing a pond inside an existing river or lake, we query the main OpenStreetMap (OSM) API.
   - The XML nodes and ways are parsed into Shapely polygons, buffered by a safety margin (e.g., $15m$ for rivers, $5m$ for lakes), and rasterized onto our DEM grid to create a boolean mask of "forbidden zones".

6. **Pond Location Candidate Selection (Depression Analysis)**
   - To find natural locations that hold water, we subtract the *raw DEM* from our *conditioned DEM*. Any cell where the elevation difference is $>0$ is part of a natural topographic depression ("bowl").
   - We group contiguous depression cells together and calculate their exact volume ($m^3$), surface area, and max depth.
   - **Candidate Scoring**: We evaluate each bowl's deepest point (the sink) based on a weighted formula: $Score = (normalized\_storage\_volume \times 0.6) + (normalized\_catchment\_area \times 0.4)$.
   - We perform a hard veto, instantly discarding any candidate whose bowl geometry touches the OSM water exclusion mask.

7. **Watershed (Catchment) Delineation via BFS**
   - Given the #1 ranked pond location (the "pour point"), we reverse the D8 flow direction graph.
   - We execute a **Breadth-First Search (BFS)** starting from the pour point, walking upstream along all incoming flow pointers. Every visited cell is flagged as part of the catchment basin.
   - The resulting raster mask of visited cells is polygonized, simplified (Douglas-Peucker algorithm), and converted into a GeoJSON format for the frontend map rendering.

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
curl -F "contour_map=@tests/fixtures/contours_1m.kml" http://localhost:8000/analyzeContour
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
