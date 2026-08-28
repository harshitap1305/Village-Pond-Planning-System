"""
Catchment delineation using Breadth-First Search (BFS) over the reverse D8 graph.
"""

from collections import deque
from typing import Tuple

import numpy as np

from src.hydrology.flow_direction import _D8_DIRECTIONS

# Build reverse map: code -> (upstream row delta, upstream col delta)
# If cell A flows into cell B, looking from B, A is at (-dr, -dc)
_REVERSE_DELTA: dict[int, tuple[int, int]] = {
    code: (-dr, -dc) for code, dr, dc in _D8_DIRECTIONS
}


def delineate_catchment(
    flow_dir: np.ndarray, pour_point_rc: Tuple[int, int]
) -> np.ndarray:
    """
    Returns a boolean mask (same shape as flow_dir) where True indicates
    cells that drain into the given pour point.

    Args:
        flow_dir: 2D array of D8 flow direction codes.
        pour_point_rc: (row, col) index of the pour point.

    Returns:
        Boolean numpy array mask of the watershed.
    """
    rows, cols = flow_dir.shape

    # 1. Build reverse adjacency graph (incoming flow)
    # incoming[r][c] = list of (nr, nc) neighbors that flow into (r, c)
    incoming: list[list[list[Tuple[int, int]]]] = [
        [[] for _ in range(cols)] for _ in range(rows)
    ]
    for r in range(rows):
        for c in range(cols):
            code = flow_dir[r, c]
            if code in _REVERSE_DELTA:
                dr, dc = _REVERSE_DELTA[code]
                # If a cell at (r,c) has code C, it flows to (r-dr, c-dc).
                # Wait, _REVERSE_DELTA contains the UPSTREAM offset.
                # Actually, the original D8 delta is the DOWNSHIFT.
                # Let's just use the logic we proved in the REPL:
                # If cell A flows to cell B, then from B's perspective, A is at an offset.
                # A easier, proven way is to do the forward pass:
                # "I am at (r,c). I flow to (nr, nc). Therefore, I am an incoming node for (nr, nc)."
                pass  # We will do this below instead of the reverse delta logic which can be confusing.

    # 1. Build reverse adjacency graph (incoming flow) by walking forward.
    incoming = [[[] for _ in range(cols)] for _ in range(rows)]

    # Forward delta map for clarity
    forward_delta = {code: (dr, dc) for code, dr, dc in _D8_DIRECTIONS}

    for r in range(rows):
        for c in range(cols):
            code = flow_dir[r, c]
            if code in forward_delta:
                dr, dc = forward_delta[code]
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    incoming[nr][nc].append((r, c))

    # 2. BFS from pour point
    mask = np.zeros((rows, cols), dtype=bool)

    # Check if pour point is in bounds
    pr, pc = pour_point_rc
    if not (0 <= pr < rows and 0 <= pc < cols):
        return mask

    queue = deque([pour_point_rc])
    mask[pour_point_rc] = True

    while queue:
        r, c = queue.popleft()
        for nr, nc in incoming[r][c]:
            if not mask[nr, nc]:
                mask[nr, nc] = True
                queue.append((nr, nc))

    return mask
