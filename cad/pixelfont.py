"""A small blocky pixel font (5x7 cells, descender row for g/p/q/y), drawn for this project.

Each glyph is a list of rows, top to bottom; '#' is a filled pixel. Row 7 is the descender.
Only the characters needed so far are defined; add more in the same style.
"""

from __future__ import annotations

import shapely.geometry as sg
from shapely.ops import unary_union

CAP_ROWS = 7  # rows 0-6 are above the baseline, row 7 hangs below it

GLYPHS: dict[str, list[str]] = {
    " ": ["...", "...", "...", "...", "...", "...", "..."],
    ".": [".", ".", ".", ".", ".", ".", "#"],
    "0": [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", "#####"],
    "2": [".###.", "#...#", "....#", "..##.", ".#...", "#....", "#####"],
    "3": [".###.", "#...#", "....#", "..##.", "....#", "#...#", ".###."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    "6": ["..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."],
    "M": ["#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"],
    "R": ["####.", "#...#", "#...#", "####.", "#..#.", "#...#", "#...#"],
    "d": ["....#", "....#", ".####", "#...#", "#...#", "#...#", ".####"],
    "e": [".....", ".....", ".###.", "#...#", "#####", "#....", ".####"],
    "g": [".....", ".....", ".####", "#...#", "#...#", ".####", "....#", "####."],
    "i": ["#", ".", "#", "#", "#", "#", "#"],
    "m": [".....", ".....", "##.#.", "#.#.#", "#.#.#", "#...#", "#...#"],
    "o": [".....", ".....", ".###.", "#...#", "#...#", "#...#", ".###."],
    "r": [".....", ".....", "#.##.", "##..#", "#....", "#....", "#...."],
    "u": [".....", ".....", "#...#", "#...#", "#...#", "#...#", ".####"],
    "z": [".....", ".....", "#####", "...#.", "..#..", ".#...", "#####"],
}


def text_width_px(text: str, spacing: int = 1) -> int:
    widths = [len(GLYPHS[ch][0]) for ch in text]
    return sum(widths) + spacing * (len(text) - 1)


def text_pixels(text: str, spacing: int = 1) -> list[tuple[int, int]]:
    """(column, row) of every filled pixel; row 0 is the top of the capitals, row 7 the descender."""
    missing = sorted({ch for ch in text if ch not in GLYPHS})
    if missing:
        raise ValueError(f"pixel font has no glyph for {missing}")
    out, x = [], 0
    for ch in text:
        glyph = GLYPHS[ch]
        for r, row in enumerate(glyph):
            out += [(x + c, r) for c, v in enumerate(row) if v == "#"]
        x += len(glyph[0]) + spacing
    return out


def text_shape(text: str, pixel: float, center_x: float, top_y: float, spacing: int = 1):
    """Text as a merged shapely shape: `pixel` mm squares, centered on center_x, cap top at top_y."""
    width = text_width_px(text, spacing) * pixel
    x0 = center_x - width / 2
    squares = [sg.box(x0 + c * pixel, top_y - (r + 1) * pixel, x0 + (c + 1) * pixel, top_y - r * pixel)
               for c, r in text_pixels(text, spacing)]
    return unary_union(squares)
