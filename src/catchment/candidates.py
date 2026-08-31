"""
Pond Candidate Location Identification — Depression Method (Module 9).

Finds suitable pond sites by detecting natural closed depressions in the DEM.
Water that falls inside a closed depression cannot escape except over the rim
(the pour point / saddle), making these the physically correct locations for
pond construction.

Algorithm overview
------------------
1. Compute the depth map: depth = filled_dem - raw_dem.
   Any cell with depth > min_depression_depth_m is inside a depression.
2. Label connected depression regions (8-connectivity).
3. Filter: discard edge-touching depressions (truncated catchment) and
   depressions smaller than min_depression_area_sqm.
4. Build the CONDITIONED DEM: filled everywhere except inside qualifying bowls.
   This eliminates noise pits that would fragment upstream catchments, while
   keeping each candidate bowl as a genuine terminal sink.
5. Route flow on the conditioned DEM (reuses Modules 7 and 8 unchanged).
6. Per bowl: locate the rim saddle (pour point), read the catchment area from
   the conditioned flow accumulation, compute storage volume and score.
7. Return the top-N candidates sorted by score, plus the conditioned routing
   outputs for downstream watershed delineation.
"""

import logging
from typing import List

import numpy as np
from pyproj import Transformer
from scipy import ndimage
from scipy.ndimage import binary_dilation

from src.config import settings
from src.hydrology.flow_accumulation import compute_flow_accumulation
from src.hydrology.flow_direction import compute_flow_direction
from src.schemas.catchment import CandidatePoint
from src.schemas.dem import DEM

_log = logging.getLogger(__name__)


def find_candidates(
    raw_dem: DEM,
    filled_dem: DEM,
    water_mask: np.ndarray | None = None,
) -> tuple[List[CandidatePoint], DEM, np.ndarray, np.ndarray]:
    """
    Identify pond candidate locations via the depression-based method.

    Args:
        raw_dem:    The original DEM before sink-filling (output of build_dem).
        filled_dem: The sink-filled DEM (output of fill_sinks).
        water_mask: Optional boolean array (same shape as DEM). When provided,
                    any depression that overlaps a True cell is hard-vetoed
                    and never returned as a candidate. Pass the output of
                    :func:`src.catchment.water_exclusion.build_water_exclusion_mask`.

    Returns:
        A 4-tuple of:
        - candidates: List of CandidatePoint, sorted best-first, capped at
                      settings.max_candidates.
        - conditioned_dem: The conditioned DEM (raw inside qualifying bowls,
                           filled elsewhere). This is the single source of truth
                           for ALL downstream routing — pass it and its routing
                           outputs to watershed delineation and metrics.
        - flow_dir_cond:   D8 flow direction array on the conditioned DEM.
        - flow_accum_cond: Flow accumulation array on the conditioned DEM.
    """
    cell_size = raw_dem.cell_size
    total_cells = raw_dem.array.size

    # ── Step A: Depression depth map ──────────────────────────────────────────
    depth = filled_dem.array - raw_dem.array  # float32, >= 0 everywhere

    # ── Step B: Label all depressions (8-connectivity required) ──────────────
    depression_mask = depth > settings.min_depression_depth_m
    labeled, n_bowls = ndimage.label(depression_mask, structure=np.ones((3, 3)))
    _log.info(
        "Found %d raw depression blobs (depth > %.2fm)",
        n_bowls,
        settings.min_depression_depth_m,
    )

    # ── Step C: First pass — identify qualifying bowl IDs ─────────────────────
    surviving_ids: List[int] = []
    for bowl_id in range(1, n_bowls + 1):
        bowl_mask = labeled == bowl_id

        # Discard edge-touching bowls: catchment would be clipped by map boundary
        if (
            bowl_mask[0, :].any()
            or bowl_mask[-1, :].any()
            or bowl_mask[:, 0].any()
            or bowl_mask[:, -1].any()
        ):
            continue

        # Discard noise: too small a footprint
        if bowl_mask.sum() * cell_size**2 < settings.min_depression_area_sqm:
            continue

        # Hard veto: any overlap with mapped water body disqualifies this bowl.
        # This prevents rivers, lakes, and reservoirs from being selected as
        # new pond sites regardless of how attractive their flow-accumulation
        # numbers look.
        if water_mask is not None and (water_mask & bowl_mask).any():
            _log.debug(
                "Bowl %d vetoed — overlaps OSM water mask (%d cells)",
                bowl_id,
                int((water_mask & bowl_mask).sum()),
            )
            continue

        surviving_ids.append(bowl_id)

    _log.info(
        "%d bowls survive edge + area filters (area >= %.0fm²)",
        len(surviving_ids),
        settings.min_depression_area_sqm,
    )

    if not surviving_ids:
        # Return empty list + the filled DEM routing (no candidates found)
        flow_dir_filled = compute_flow_direction(filled_dem)
        flow_accum_filled = compute_flow_accumulation(flow_dir_filled, filled_dem)
        return [], filled_dem, flow_dir_filled, flow_accum_filled

    # ── Step D: Build conditioned DEM ─────────────────────────────────────────
    # Conditioned = raw inside qualifying bowls, filled everywhere else.
    # This removes noise pits (which fragment upstream catchments) while
    # keeping candidate bowls as genuine terminal sinks.
    qualifying_mask = np.zeros_like(raw_dem.array, dtype=bool)
    for bowl_id in surviving_ids:
        qualifying_mask |= labeled == bowl_id

    conditioned_array = np.where(
        qualifying_mask, raw_dem.array, filled_dem.array
    ).astype(np.float32)
    conditioned_dem = DEM(
        array=conditioned_array,
        origin_x=raw_dem.origin_x,
        origin_y=raw_dem.origin_y,
        cell_size=raw_dem.cell_size,
        crs=raw_dem.crs,
    )

    # ── Step E: Flow routing on conditioned DEM ───────────────────────────────
    flow_dir_cond = compute_flow_direction(conditioned_dem)
    flow_accum_cond = compute_flow_accumulation(flow_dir_cond, conditioned_dem)

    # ── Step F: UTM → WGS84 transformer (shared for all candidates) ──────────
    transformer = Transformer.from_crs(raw_dem.crs, "EPSG:4326", always_xy=True)

    # ── Step G: Per-bowl scoring loop ─────────────────────────────────────────
    candidates: List[CandidatePoint] = []

    for bowl_id in surviving_ids:
        bowl_mask = labeled == bowl_id

        # G1. Pour point = saddle on the rim (lowest elevation on boundary ring).
        # Boundary ring: cells immediately surrounding the bowl but outside it.
        # Verified: raw_dem == filled_dem at all boundary ring cells (rim never raised).
        boundary_ring = (
            binary_dilation(bowl_mask, structure=np.ones((3, 3))) & ~bowl_mask
        )
        pour_idx = np.unravel_index(
            np.argmin(np.where(boundary_ring, raw_dem.array, np.inf)),
            raw_dem.array.shape,
        )

        # sink cells. Since flow_dir_cond == 0 for all terminal cells, their
        # upstream catchments are strictly disjoint, so summing them is safe.
        # We must seed from ALL internal sinks, not just the absolute deepest one,
        # because the raw DEM interior has noise pits that trap incoming streams.
        sink_cells_mask = bowl_mask & (flow_dir_cond == 0)
        sink_rcs = list(zip(*np.where(sink_cells_mask)))
        catchment_cells = int(flow_accum_cond[sink_cells_mask].sum())

        # G3. Catchment area filter
        catchment_ha = catchment_cells * cell_size**2 / 10_000
        if catchment_ha < settings.min_catchment_area_ha:
            continue

        # G4. Storage volume: topographic fill volume (upper-bound estimate)
        storage_m3 = float(depth[bowl_mask].sum()) * cell_size**2

        # G5. Depression footprint area
        depression_area_ha = float(bowl_mask.sum() * cell_size**2 / 10_000)

        # G6. Depression depth (max fill depth inside the bowl)
        depression_depth_m = float(depth[bowl_mask].max())

        # G7. Score: normalized by total DEM cell count (stable, size-independent)
        score = catchment_cells / total_cells

        # G8. Pour point coords (rim saddle)
        pour_row, pour_col = pour_idx
        x = raw_dem.origin_x + pour_col * cell_size + cell_size / 2.0
        y = raw_dem.origin_y - pour_row * cell_size - cell_size / 2.0
        lon, lat = transformer.transform(x, y)

        candidates.append(
            CandidatePoint(
                lat=lat,
                lon=lon,
                elevation=float(raw_dem.array[pour_row, pour_col]),
                score=score,
                depression_depth_m=depression_depth_m,
                depression_area_ha=depression_area_ha,
                catchment_area_ha=catchment_ha,
                estimated_storage_m3=storage_m3,
                had_flat_bottom=len(sink_rcs) > 1,
                bowl_sink_rcs=sink_rcs,
            )
        )

    _log.info(
        "%d candidates pass catchment filter (>= %.2f ha)",
        len(candidates),
        settings.min_catchment_area_ha,
    )

    # Sort best-first and truncate
    candidates.sort(key=lambda c: c.score, reverse=True)
    return (
        candidates[: settings.max_candidates],
        conditioned_dem,
        flow_dir_cond,
        flow_accum_cond,
    )
