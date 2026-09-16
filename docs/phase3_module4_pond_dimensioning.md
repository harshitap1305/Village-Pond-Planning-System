# Module 4 — Pond Dimensioning & Storage Capacity

## Overview
Module 4 converts the hydrological outputs from Modules 2 and 3 into a
**concrete physical pond design**: water depth, embankment height, storage
breakdown, and feasibility assessment — all grounded in Indian Standards (IS 5477)
and NABARD/MGNREGS practice guidelines.

## The Two-Constraint Reconciliation

Module 4 answers the question:
> "What size pond should we build, given both how much water arrives *and* how much the bowl can physically hold?"

Two independent constraints bound the design:

| Constraint | Value Source | Represents |
|---|---|---|
| **Hydrological supply** | `RunoffEstimate.annual_avg_m3 × 0.40` | Water available for capture |
| **Topographic capacity** | `CandidatePoint.estimated_storage_m3` | Physical bowl fill volume (DEM) |

```python
live_storage_m3 = min(
    annual_runoff_m3 × target_capture_fraction,   # 40% of runoff
    topographic_storage_m3,                        # DEM fill volume
)
```

The `constrained_by` field in the response tells the client which constraint won:
- `"hydrology"` — the bowl is large enough; runoff limits the design.
- `"topography"` — the bowl isn't big enough to store 40% of runoff.
- `"depth_min"` / `"depth_max"` — depth clamp was the final binding constraint.

## Storage Breakdown (IS 5477)

Following IS 5477 Parts 2, 3, and 4:

```
live_storage     [IS 5477 Part 3 — useful storage]
  ÷ (1 - evap_fraction - seepage_fraction)
= gross_storage  [inflated to cover annual losses]
  × (1 + dead_storage_fraction)
= total_storage  [IS 5477 Part 2 — includes sediment allowance]
```

**Default loss fractions** (can be overridden via `.env`):
| Loss type | Fraction | Basis |
|---|---|---|
| Evaporation | 15% | CWC data: 1000–2000mm/yr for central India |
| Seepage (unlined) | 10% | IS 5477 + NABARD unlined farm pond allowance |
| Dead storage | 10% of gross | IS 5477 Part 2 (50-year sediment design life) |

## Depth Calculation

The bowl's footprint (`depression_area_ha`) is used as the pond surface area at
full supply level (FSL). Depth is back-solved using:

```
total_storage_m3
water_depth_m = ─────────────────────────────
                surface_area_m2 × shape_factor
```

**Shape factor = 0.4** (between cone=0.33 and cylinder=1.0):
Validated against the prismoidal formula:
```
V = h/3 × (A_top + A_bottom + √(A_top × A_bottom))
```
with `A_bottom ≈ 0.3 × A_top` — typical for natural depression bowls.

The result is **clamped** to [1.5m, 4.0m]:
- **Min 1.5m**: MGNREGS minimum; below this, ponds dry out rapidly and create mosquito-breeding margins.
- **Max 4.0m**: IS 12169 safety limit for unlined earthen embankments.

## Embankment Design

```
embankment_height_m = water_depth_m + freeboard_m
                    = water_depth_m + 0.5
```

Standard parameters used:
| Parameter | Value | Standard |
|---|---|---|
| Freeboard | 0.5 m | IS 5477 Part 4 / MOEF |
| Side slope | 2:1 H:V | NABARD (conservative; safe for loam soils) |
| Top width | 1.5 m | IS 12169 / NABARD (for bund height < 10m) |

## Output Schema: `PondDesign`

```json
{
  "live_storage_m3": 3200.0,
  "dead_storage_m3": 468.1,
  "gross_storage_m3": 4267.0,
  "total_storage_m3": 4735.1,
  "water_depth_m": 2.65,
  "embankment_height_m": 3.15,
  "surface_area_m2": 4500.0,
  "embankment_top_width_m": 1.5,
  "target_capture_fraction": 0.4,
  "freeboard_m": 0.5,
  "side_slope": 2.0,
  "shape_factor": 0.4,
  "evaporation_loss_fraction": 0.15,
  "seepage_loss_fraction": 0.10,
  "topographic_storage_m3": 12000.0,
  "annual_runoff_m3": 8000.0,
  "constrained_by": "hydrology",
  "fills_in_wet_season": true,
  "supply_deficit": false
}
```

## Feasibility Flags

| Flag | Meaning |
|---|---|
| `fills_in_wet_season: true` | Monsoon runoff alone (Jun–Sep) can fill the pond — the site doesn't need pre-monsoon supplementation. |
| `supply_deficit: true` | Annual runoff < live storage — the pond won't fill to full capacity every year on average. Site still viable but should manage expectations. |

## Pipeline Position

Step 7d in `analysis_service.py`, immediately after Step 7c (runoff estimation).

```
Module 3 (runoff_estimate)  →  7d recommend_pond_design()  →  PondDesign
Phase 2 (selected candidate)
  .estimated_storage_m3
  .depression_area_ha
```

Fail-open: if `runoff_estimate` is `None`, `pond_design` is `None` in the response
(no exception is raised; the pipeline continues).

## Authority References

- **IS 5477 Parts 2, 3, 4**: Dead, Live, and Flood storage definitions
- **IS 12169**: Criteria for design of small embankment dams
- **NABARD Farm Pond Design Guidelines** (NABARD Circular 157/2016)
- **MGNREGS Model Estimates** for farm ponds: standard 10m×10m×3m to 15m×15m×3m
- **MOEF Farm Pond Technical Manual**: freeboard, seepage, side slope standards
- **Central Water Commission (CWC)**: open water evaporation data for Indian reservoirs
