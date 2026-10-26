"""Top-down PNG maps of the built world: the roofs view, and a floor plan cut just above the ground."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from kanto.world import MIN_Y, World

COLORS = [  # first matching keyword wins
    ("magenta_glazed", (200, 60, 200)), ("water", (50, 110, 220)), ("waterlily", (40, 140, 40)),
    ("leaves", (40, 120, 40)), ("short_grass", (90, 170, 60)), ("tall_grass", (70, 150, 50)),
    ("grass_path", (190, 160, 100)), ("grass_block", (110, 180, 80)), ("sand", (225, 210, 150)),
    ("smooth_sandstone", (235, 215, 160)), ("log", (110, 80, 50)), ("barrier", (255, 0, 0)),
    ("mangrove", (150, 50, 40)), ("red_mushroom", (220, 30, 30)), ("red", (200, 40, 40)),
    ("light_blue", (120, 180, 230)), ("blue", (50, 70, 190)), ("pink", (240, 150, 190)),
    ("yellow", (240, 220, 60)), ("orange", (220, 120, 40)), ("lime", (130, 210, 60)),
    ("green", (60, 120, 40)), ("black", (25, 25, 25)), ("light_gray", (170, 170, 170)), ("gray", (90, 90, 90)),
    ("white", (240, 240, 240)), ("quartz", (235, 230, 225)), ("deepslate", (70, 70, 80)),
    ("brick", (160, 80, 60)), ("granite", (170, 110, 90)), ("gold", (250, 210, 50)), ("iron", (215, 215, 215)),
    ("glass", (180, 220, 240)), ("bookshelf", (130, 90, 50)), ("spruce", (110, 80, 50)),
    ("oak", (180, 140, 90)), ("fence", (160, 120, 80)), ("door", (140, 100, 60)), ("andesite", (140, 140, 140)),
    ("stone", (130, 130, 130)), ("sign", (200, 170, 110)), ("button", (90, 90, 90)), ("bed", (200, 40, 40)),
    ("terracotta", (215, 190, 170)), ("dirt", (120, 85, 60)), ("sea_lantern", (210, 240, 230)),
    ("poppy", (220, 30, 30)), ("dandelion", (250, 230, 50)), ("cornflower", (90, 110, 230)),
    ("daisy", (245, 245, 245)), ("azalea", (90, 160, 70)), ("carpet", (200, 60, 60)),
]


def _color(name: str) -> tuple[int, int, int]:
    for kw, c in COLORS:
        if kw in name:
            return c
    return (255, 0, 255)


def render(w: World, bounds, out: Path, cut: dict | None = None, scale: int = 3) -> Path:
    """cut: {(x, z): max y to show} for a floor plan; None shows the top of every column."""
    import matplotlib.pyplot as plt

    x0, z0, x1, z1 = bounds
    lut = np.array([_color(b.name) if i else (0, 0, 0) for i, b in enumerate(w.palette)], np.uint8)
    img = np.zeros((z1 - z0 + 1, x1 - x0 + 1, 3), np.uint8)
    for (cx, cz), c in w.chunks.items():
        for lx in range(16):
            for lz in range(16):
                x, z = cx * 16 + lx, cz * 16 + lz
                if not (x0 <= x <= x1 and z0 <= z <= z1):
                    continue
                col = c[lx, :, lz]
                if cut is not None:
                    col = col[:cut.get((x, z), 400) - MIN_Y + 1]
                nz = np.nonzero(col)[0]
                if len(nz):
                    img[z - z0, x - x0] = lut[col[nz[-1]]]
    img = np.kron(img, np.ones((scale, scale, 1), np.uint8))
    plt.imsave(out, img)
    return out
