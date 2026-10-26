"""Viridian Gym spinner-tile maze (the FireRed/LeafGreen puzzle): arrow tiles slide you until you reach a
plain tile. Most of the floor pushes you back to the entrance; a few hidden conveyors carry you to rest
islands and on to the Gym Leader.

The grid is rows north -> south, columns west -> east:
  '#' wall, '.' floor, '^' 'v' '<' '>' arrow tiles, 'G' the opening to the leader's platform.
`solve` uses the same rules as the script in the behavior pack, so the tests prove the maze is winnable.
"""

from __future__ import annotations

from collections import deque
from itertools import pairwise

COLS, ROWS = 31, 29
DIRS = {"^": (0, -1), "v": (0, 1), "<": (-1, 0), ">": (1, 0)}
ENTRANCE = (15, 28)  # (col, row)


def _paint(g: list[list[str]], cells: list[tuple[int, int]]) -> None:
    """Arrows along a path of (col, row) corners; each tile points to the next one. Ends on the last corner,
    which is left as it is (floor or another arrow)."""
    pts = []
    for (c0, r0), (c1, r1) in pairwise(cells):
        dc, dr = (c1 > c0) - (c1 < c0), (r1 > r0) - (r1 < r0)
        assert dc == 0 or dr == 0, "conveyor legs must be straight"
        c, r = c0, r0
        while (c, r) != (c1, r1):
            pts.append((c, r, dc, dr))
            c, r = c + dc, r + dr
    arrow = {v: k for k, v in DIRS.items()}
    for c, r, dc, dr in pts:
        g[r][c] = arrow[(dc, dr)]


def _floor(g, c0, r0, c1, r1):
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            g[r][c] = "."


def layout() -> list[str]:
    g = [["v"] * COLS for _ in range(ROWS)]
    for r in range(ROWS):
        g[r][0] = g[r][COLS - 1] = "#"
    g[0] = ["#"] * COLS
    g[0][15] = "G"
    _floor(g, 1, 26, 29, 28)          # entrance hall
    _floor(g, 3, 16, 6, 18)           # island A (west)
    _floor(g, 14, 10, 18, 11)         # island B (middle)
    _floor(g, 12, 1, 18, 2)           # island C, below the leader
    # entrance -> A (the real start), plus two decoys that loop back to the entrance hall
    _paint(g, [(4, 25), (4, 19), (4, 18)])
    _paint(g, [(15, 25), (15, 19), (28, 19), (28, 25), (28, 26)])
    _paint(g, [(26, 25), (26, 21), (7, 21), (7, 22)])
    # A -> B, and a decoy going north from A that dumps you on the far west column
    _paint(g, [(7, 17), (16, 17), (16, 12), (16, 11)])
    _paint(g, [(4, 15), (4, 8), (1, 8), (1, 9)])
    # B -> C around the east side; the tempting straight-north tile swerves off and drops you back
    _paint(g, [(19, 11), (24, 11), (24, 3), (18, 3), (18, 2)])
    _paint(g, [(16, 9), (16, 5), (2, 5), (2, 6)])
    return ["".join(row) for row in g]


def slide(grid: list[str], c: int, r: int) -> tuple[int, int]:
    """Where a player who stepped onto (c, r) comes to rest. Raises on a loop."""
    seen = set()
    while grid[r][c] in DIRS:
        if (c, r) in seen:
            raise ValueError(f"arrow loop at {(c, r)}")
        seen.add((c, r))
        dc, dr = DIRS[grid[r][c]]
        nc, nr = c + dc, r + dr
        if not (0 <= nc < COLS and 0 <= nr < ROWS) or grid[nr][nc] == "#":
            break  # pushed against a wall: stuck on this tile, free to walk off
        c, r = nc, nr
    return c, r


def solve(grid: list[str], start=ENTRANCE) -> dict[tuple[int, int], tuple[int, int] | None]:
    """Breadth-first search over resting spots; returns {spot: previous spot}."""
    prev = {start: None}
    q = deque([start])
    while q:
        c, r = q.popleft()
        for dc, dr in DIRS.values():
            nc, nr = c + dc, r + dr
            if not (0 <= nc < COLS and 0 <= nr < ROWS) or grid[nr][nc] == "#":
                continue
            rest = slide(grid, nc, nr)
            if rest not in prev:
                prev[rest] = (c, r)
                q.append(rest)
    return prev


def goal(grid: list[str]) -> tuple[int, int]:
    return grid[0].index("G"), 0
