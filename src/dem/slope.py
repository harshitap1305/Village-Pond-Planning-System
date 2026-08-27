"""
Topographic slope calculation.

Calculates the slope angle in degrees for every cell in the DEM.
Uses numpy gradient to compute partial derivatives.
"""

import numpy as np

from src.schemas.dem import DEM


def compute_slope_deg(dem: DEM) -> np.ndarray:
    """
    Compute the slope of the DEM in degrees.

    Uses the formula: slope = arctan(sqrt((∂z/∂x)² + (∂z/∂y)²))

    Args:
        dem: The input DEM (should be sink-filled, though not strictly required).

    Returns:
        A 2D numpy array of the same shape containing slope in degrees (0 to 90).
    """
    # np.gradient returns gradients along axes.
    # For a 2D array, axis 0 is rows (Y direction), axis 1 is cols (X direction).
    # Since cell_size is in metres, the gradient is dimensionless (m/m).
    dy, dx = np.gradient(dem.array, dem.cell_size, dem.cell_size)

    # slope in radians
    slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))

    # Convert to degrees for easier thresholding in pond candidate selection
    slope_deg = np.degrees(slope_rad)

    return slope_deg.astype(np.float32)
