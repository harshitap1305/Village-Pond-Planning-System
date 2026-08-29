# Module 11: Catchment Metrics & Area Calculation

## Overview

The Catchment Metrics module (`src/catchment/metrics.py`) is responsible for calculating geometric and topographical statistics of the delineated watershed. This information is crucial for the final application, as it provides the core data (catchment area in hectares) used to size the village pond.

## Design Decisions

- **Vectorized Mathematics**: Calculates properties across the entire masked catchment instantaneously using `numpy` functions (`np.min`, `np.max`, `np.mean`) instead of Python loops.
- **Hectare Conversion Formula**: Area is calculated explicitly as `(cell_count * cell_size * cell_size) / 10,000`. This is mathematically rigorous since the DEM operates in a metric, projected CRS where cells are perfectly square.
- **D8 Flow Consistency Check**: Added an `assert_area_consistency` helper that compares the final polygon's cell count against the flow accumulation value at the pour point. On real data, these usually differ exactly by 1 (the pour point cell itself is included in the BFS polygon but not the flow accumulation count). This serves as a vital cross-check to catch algorithmic boundary-condition bugs.

## Core Components

### 1. `CatchmentMetrics` (Schema)
Located in `src/schemas/catchment.py`. This Pydantic model holds the statistical summary:
- `area_ha`: Total catchment area in hectares.
- `cell_count`: Total number of DEM cells within the catchment boundary.
- `elevation_stats`: Dictionary containing the `min`, `max`, and `mean` elevations.
- `slope_stats`: Dictionary containing the `min`, `max`, and `mean` slopes in degrees.

### 2. `compute_metrics`
Located in `src/catchment/metrics.py`. Extracts values from the DEM elevation and slope arrays based on the boolean mask output from the BFS traversal in Module 10.

### 3. `assert_area_consistency`
A self-healing sanity check that validates the mathematical guarantees of the D8 flow routing model. Raises a warning if the catchment size fundamentally disagrees with the water accumulation model.

## Testing

Tested against `tests/fixtures/toy_dem.py`. The unit tests mathematically verify the exact Hectare conversion rate and expected slope characteristics. A special edge case for correct slope testing (using `math.atan(1 / math.sqrt(2))`) was resolved to align with the finite-difference method in `src/dem/slope.py`.
