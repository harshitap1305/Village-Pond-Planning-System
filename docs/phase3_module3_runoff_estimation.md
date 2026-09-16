# Module 3 — Runoff Estimation

## Overview
Module 3 converts the 10-year historical rainfall data (from Module 2) into
estimated runoff volumes that will actually reach and fill the selected pond site.
Not all rain becomes runoff — a significant fraction infiltrates soil, evaporates,
or is intercepted by vegetation before reaching the bowl.

## Method: SCS Curve Number (SCS-CN)

The module implements the **USDA SCS Curve Number method** (TR-55, 1986) applied
month-by-month to the 10-year monthly rainfall averages from ERA5-Land.

### Core Equations

```
S  = (25400 / CN) - 254      [mm — potential maximum retention]
Ia = 0.2 × S                  [mm — initial abstraction threshold]

For daily rainfall P (mm):
  if P > Ia:
    Q = (P - Ia)² / (P - Ia + S)   [mm runoff]
  else:
    Q = 0
```

### Why SCS-CN (not Rational Method)

| Method | Output | Suitability |
|---|---|---|
| Rational (`Q = CiA`) | Peak discharge (m³/s) | ❌ Gives flow rate, not volume |
| Simple coefficient (`V = C × P × A`) | Annual volume | ⚠ Ignores intensity threshold |
| **SCS-CN** | Event runoff depth → annual volume | ✅ Physically correct |

The Rational Method gives peak discharge — not what we need. The SCS-CN method
captures the critical **threshold effect**: light daily drizzle (P < Ia) produces
zero runoff, while intense storm events produce disproportionately large runoff.

### Monthly-Distributed Daily Application

Monthly rainfall totals are divided evenly across the days of each month,
creating a synthetic daily series. The SCS-CN event formula is applied to each
representative daily value, then summed across the month. This preserves the
threshold effect while requiring only monthly averages (no daily API needed).

## Curve Number (CN) Defaults

| Land Cover | HSG A | HSG B | HSG C | HSG D |
|---|---|---|---|---|
| `mixed_agriculture` | 59 | **71** | 79 | 83 |
| `woodland_scrub` | 36 | 60 | 73 | 79 |
| `grassland` | 39 | 61 | 74 | 80 |
| `built_up` | 77 | **85** | 90 | 92 |
| `rocky_barren` | 45 | 66 | 77 | 83 |

**Default**: `mixed_agriculture` + `HSG B` → **CN = 71**

HSG "B" covers the majority of Indian village sites:
- Deccan basalt / laterite (Karnataka, Maharashtra, Chhattisgarh)
- Red loam soils (MP, Rajasthan, Andhra Pradesh)
- Indo-Gangetic alluvium (UP, Bihar, Punjab)

Override via `DEFAULT_HSG` in `.env` for clay-heavy (`C`/`D`) or sandy (`A`) terrain.

### Built-up Catchment Detection

If more than 30% of bowl cells (from the Module 1 land exclusion mask) are
classified as built-up, the catchment is treated as urban-dominant and CN is
bumped to 85 (HSG B). This uses already-computed data — no new external calls.

## Fallback

If monthly rainfall data is unavailable, the module falls back to:
```
Volume = C_fallback × (annual_avg_mm / 1000) × area_m²
```
with `C_fallback = 0.30` (IS 5477 Part 1 range: 0.25–0.40 for mixed agriculture).
`method` field in the response is set to `"rational_annual_fallback"` in this case.

## Output Schema: `RunoffEstimate`

```json
{
  "annual_avg_m3": 18450.5,
  "wet_season_avg_m3": 16200.0,
  "dry_season_avg_m3": 2250.5,
  "peak_month": 8,
  "runoff_depth_mm": 369.0,
  "curve_number": 71,
  "land_cover_assumed": "mixed_agriculture",
  "hsg_assumed": "B",
  "catchment_area_ha": 5.0,
  "method": "scs_cn_monthly_distributed"
}
```

## Pipeline Position

Step 7c in `analysis_service.py`, immediately after Step 7b (rainfall retrieval).
Inputs taken from:
- `selected.catchment_area_ha` — from Phase 2 candidate detection
- `rainfall_stats.monthly_avg_mm` — from Module 2 (ERA5-Land or NASA POWER)
- `land_result.mask` — from Module 1 (built-up fraction)

## Authority References

- USDA TR-55 (1986), Table 2-2 — CN values
- USDA NEH Part 630, Chapter 10 — SCS-CN event equations
- NRSC/ISRO IMSD Technical Guidelines for Watershed Assessment in India
- IS 5477 Part 1 — Methods for Fixing the Capacities of Low Dams
