"""Vectorize the ornament concept art (PNG) into SVGs for modeling in Fusion 360.

A faithful trace (no thickening, no filling): the black areas of the art become closed filled paths.
For each design:
- <name>-lines.svg  the black linework (closed profiles; even-odd fill, so holes stay holes)
- <name>-back.svg   the ornament's outer shape (silhouette) with the hanging hole cut out
- <name>.svg        both, in two groups ("back" in light gray, "lines" in black), same coordinates
Sized in millimeters: the ball is BODY_D wide (the soldier, which has no ball, is SOLDIER_H tall).

Run: python -m cad.ornament_svg [--src output/ornament-art] [--out output/ornament-svg]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import shapely.geometry as sg
from PIL import Image
from shapely.affinity import scale, translate
from shapely.ops import unary_union

from cad.ornament_trace import black_shapes

BODY_D = 76.0
SOLDIER_H = 70.0             # fits inside a 76 mm ball ornament later
SIMPLIFY_MM = 0.03           # keeps curves smooth while keeping point counts reasonable for Fusion
MIN_AREA_MM2 = 0.05          # drop specks


def _rings(geom):
    for p in getattr(geom, "geoms", [geom]):
        if isinstance(p, sg.Polygon) and not p.is_empty:
            yield p.exterior
            yield from p.interiors


def path_d(geom, height: float) -> str:
    """SVG path data (mm), flipping y so +y is down as SVG expects."""
    parts = []
    for ring in _rings(geom):
        xy = np.asarray(ring.coords)[:-1]
        pts = " ".join(f"{x:.3f},{height - y:.3f}" for x, y in xy)
        parts.append(f"M{pts}Z")
    return " ".join(parts)


def svg(layers: list[tuple[str, object, str]], w: float, h: float) -> str:
    body = "\n".join(f'  <g id="{name}"><path fill="{fill}" fill-rule="evenodd" d="{path_d(g, h)}"/></g>'
                     for name, g, fill in layers)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.3f}mm" height="{h:.3f}mm" '
            f'viewBox="0 0 {w:.3f} {h:.3f}">\n{body}\n</svg>\n')


def vectorize(png: Path, name: str):
    img = np.asarray(Image.open(png).convert("L"), dtype=float) / 255.0
    black = black_shapes(img)
    parts = list(getattr(black, "geoms", [black]))
    rim = max(parts, key=lambda g: sg.Polygon(g.exterior).area)
    whole = sg.Polygon(rim.exterior)
    if name == "soldier":                                   # no ball: the figure's own outline
        whole = unary_union([sg.Polygon(g.exterior) for g in parts])
    x0, y0, x1, y1 = whole.bounds
    k = SOLDIER_H / (y1 - y0) if name == "soldier" else BODY_D / (x1 - x0)
    # hanging hole: an enclosed white space near the top, small
    hole = sg.Polygon()
    if name != "soldier":
        inside_white = whole.difference(black)
        top_band = y1 - 0.15 * (y1 - y0)
        holes = [g for g in getattr(inside_white, "geoms", [inside_white])
                 if g.centroid.y > top_band and g.area < 0.01 * whole.area]
        hole = max(holes, key=lambda g: g.area) if holes else hole

    def mm(g):
        return translate(scale(g, k, k, origin=(0, 0)), -x0 * k, -y0 * k).simplify(SIMPLIFY_MM)

    lines = mm(black)
    lines = unary_union([g for g in getattr(lines, "geoms", [lines]) if g.area >= MIN_AREA_MM2])
    back = mm(whole).difference(mm(hole))
    w, h = (x1 - x0) * k, (y1 - y0) * k
    return back, lines, w, h


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ornament concept art -> SVG for Fusion 360")
    ap.add_argument("--src", type=Path, default=Path("output/ornament-art"))
    ap.add_argument("--out", type=Path, default=Path("output/ornament-svg"))
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    report = {}
    for png in sorted(args.src.glob("*/*/gen-1.png")):
        name = png.parts[-3]
        back, lines, w, h = vectorize(png, name)
        (args.out / f"{name}-lines.svg").write_text(svg([("lines", lines, "#000000")], w, h))
        (args.out / f"{name}-back.svg").write_text(svg([("back", back, "#000000")], w, h))
        (args.out / f"{name}.svg").write_text(svg([("back", back, "#DDDDDD"), ("lines", lines, "#000000")], w, h))
        n_pts = sum(len(r.coords) for r in _rings(lines))
        report[name] = {"size_mm": [round(w, 1), round(h, 1)], "line_profiles": len(getattr(lines, "geoms", [lines])),
                        "points": n_pts}
    (args.out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
