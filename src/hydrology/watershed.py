"""
Catchment delineation using Breadth-First Search (BFS) over the reverse D8 graph.
"""

from collections import deque
from typing import Sequence, Tuple

import numpy as np

from src.hydrology.flow_direction import _D8_DIRECTIONS

# Forward delta map: code -> (row_delta, col_delta)
_FORWARD_DELTA: dict[int, tuple[int, int]] = {
    code: (dr, dc) for code, dr, dc in _D8_DIRECTIONS
}


def delineate_catchment(
    flow_dir: np.ndarray,
    seed_cells: Sequence[Tuple[int, int]],
) -> np.ndarray:
    """
    Returns a boolean mask (same shape as flow_dir) where True indicates
    cells that drain into any of the given seed cells.

    Uses BFS over the reverse D8 graph (walking upstream from seeds).

    Args:
        flow_dir:   2D array of D8 flow direction codes.
        seed_cells: One or more (row, col) indices to seed the BFS from.
                    Pass a list with a single element for the common single-sink case.
                    Pass all tied minimum-elevation cells for flat-bottomed bowls
                    to ensure the full watershed is captured regardless of
                    which cell upstream tie-breaks happened to favour.

    Returns:
        Boolean numpy array mask of the watershed.
    """
    rows, cols = flow_dir.shape

    # 1. Build reverse adjacency graph via a forward pass.
    #    For each cell (r,c) that flows to (nr,nc), record (r,c) as an
    #    incoming neighbor of (nr,nc).
    incoming: list[list[list[Tuple[int, int]]]] = [
        [[] for _ in range(cols)] for _ in range(rows)
    ]
    for r in range(rows):
        for c in range(cols):
            code = flow_dir[r, c]
            if code in _FORWARD_DELTA:
                dr, dc = _FORWARD_DELTA[code]
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    incoming[nr][nc].append((r, c))

    # 2. BFS from all seed cells simultaneously.
    mask = np.zeros((rows, cols), dtype=bool)
    queue: deque[Tuple[int, int]] = deque()

    for sr, sc in seed_cells:
        if 0 <= sr < rows and 0 <= sc < cols and not mask[sr, sc]:
            mask[sr, sc] = True
            queue.append((sr, sc))

    while queue:
        r, c = queue.popleft()
        for nr, nc in incoming[r][c]:
            if not mask[nr, nc]:
                mask[nr, nc] = True
                queue.append((nr, nc))

    return mask
