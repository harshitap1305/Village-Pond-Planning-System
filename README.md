# Village Pond Planning System

AI-assisted web tool for identifying optimal rainwater harvesting pond locations in rural villages.

## Overview

Accepts KML/KMZ contour data for a village area and returns:
- **Ranked candidate pond locations** (lat/lon + score)
- **Estimated catchment polygon** (GeoJSON)
- **Runoff volume estimate** based on historical rainfall
- **Recommended pond depth and storage capacity**

Built for the CSD Assignment — AI-based Village Pond Planning System.

## Technology Stack

- **Backend**: Python 3.12 · FastAPI · uvicorn
- **Geospatial**: NumPy · SciPy · PyProj · Rasterio · Shapely · pysheds
- **KML Parsing**: lxml · fastkml
- **Config**: pydantic-settings (12-factor env-based)

## Quick Start

### Prerequisites
- Python 3.11+
- `build-essential` and `libgdal-dev` (required for RichDEM)
  ```bash
  sudo apt-get install build-essential libgdal-dev
  ```

### Setup

```bash
# Clone the repo
git clone git@github.com:harshitap1305/Village-Pond-Planning-System.git
cd Village-Pond-Planning-System

# Create and activate virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment config
cp .env.example .env
```

### Run the API

```bash
uvicorn src.api.main:app --reload
# Interactive API docs: http://localhost:8000/docs
```

### Run Tests

```bash
pytest
# With coverage:
pytest --cov=src --cov-report=term-missing
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

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/analyzeContour` | Upload KML/KMZ, returns candidates + catchment |
| `GET`  | `/health` | Health check |
| `GET`  | `/docs` | Interactive Swagger UI |

## License

MIT
