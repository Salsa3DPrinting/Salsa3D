"""Trace black-on-white ornament art (e.g. Meshy concept art) into a printable color-in ornament.

Steps: threshold the image -> filled contours of the black lines (contourpy) -> ornament outline (the
outer rim, with the hanging ring's hole cut through) -> scale so the ball is BODY_D wide -> thicken lines
to at least LW -> fill any white space a marker can't get into solid black -> 3D: white back BACK_T thick
with the black lines LINE_T proud on top (the same build as cad/coloring_ornaments.py).

Run: python -m cad.ornament_trace IMAGE NAME [--out DIR] [--body 76]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import shapely.geometry as sg
from shapely.affinity import scale, translate
from shapely.ops import unary_union

from cad.coloring_ornaments import BACK_T, BLACK, LINE_T, LW, MARKER_D, RIM_W, WHITE, check, outline, white_regions

BODY_D = 76.0
THRESHOLD = 0.5              # gray level (0 black .. 1 white) between line and paper
MIN_SPECK_MM2 = 0.3          # drop black specks smaller than this


def black_shapes(img: np.ndarray):
    """Black areas of a grayscale image (0..1, row 0 at the top) as shapely polygons in pixel units, y up."""
    import contourpy
    from scipy import ndimage

    smooth = ndimage.gaussian_filter(img, 0.8)
    gen = contourpy.contour_generator(z=smooth[::-1], fill_type=contourpy.FillType.OuterOffset)
    polys = []
    pts, offsets = gen.filled(-1.0, THRESHOLD)
    for p, off in zip(pts, offsets):
        rings = [p[off[i]:off[i + 1]] for i in range(len(off) - 1)]
        if len(rings[0]) < 4:
            continue
        poly = sg.Polygon(rings[0], [r for r in rings[1:] if len(r) >= 4]).buffer(0)
        if not poly.is_empty:
            polys.append(poly)
    return unary_union(polys)


def trace(path: Path, body_d: float = BODY_D):
    from PIL import Image

    img = np.asarray(Image.open(path).convert("L"), dtype=float) / 255.0
    black = black_shapes(img)
    parts = list(getattr(black, "geoms", [black]))
    # The ornament outline: the biggest black shape's outer edge (the rim), with everything inside it.
    rim = max(parts, key=lambda g: sg.Polygon(g.exterior).area)
    whole = sg.Polygon(rim.exterior)
    x0, y0, x1, y1 = whole.bounds
    # Hanging hole: a white space enclosed near the top, above the ball (the ring's eye).
    inside_white = whole.difference(black)
    top_band = y1 - 0.15 * (y1 - y0)
    holes = [g for g in getattr(inside_white, "geoms", [inside_white])
             if g.centroid.y > top_band and g.area < 0.01 * whole.area]
    hole = max(holes, key=lambda g: g.area) if holes else sg.Polygon()
    # Scale: the ball is the widest part.
    k = body_d / (x1 - x0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    def mm(g):
        return translate(scale(g, k, k, origin=(cx, cy)), -cx, -cy)

    back = mm(whole).difference(mm(hole).buffer(0.1))
    lines = mm(black).intersection(back)
    lines = unary_union([g for g in getattr(lines, "geoms", [lines]) if g.area >= MIN_SPECK_MM2])
    # Stroke width estimate (thin shapes: 2 * area / perimeter), then thicken to at least LW.
    est = 2 * lines.area / lines.length
    grow = max(0.0, (LW - est) / 2)
    lines = lines.buffer(grow, quad_segs=6).intersection(back)
    lines = unary_union([lines, outline(back, RIM_W).intersection(back),
                         outline(mm(hole).buffer(0.1), LW).intersection(back)])
    back = back.simplify(0.04)
    lines = lines.simplify(0.04).intersection(back)
    # White spaces too small for a marker tip become solid black (after simplifying, so no slivers remain).
    filled = [g for g in white_regions(back, lines) if g.buffer(-MARKER_D / 2).is_empty]
    lines = unary_union([lines, *[g.buffer(0.05) for g in filled]]).intersection(back)
    info = {"source": str(path), "px_to_mm": round(k, 4), "stroke_mm_traced": round(est, 2),
            "stroke_grown_mm_per_side": round(grow, 2), "small_spaces_filled": len(filled),
            "hanging_hole_mm": round(2 * np.sqrt(mm(hole).area / np.pi), 1) if not hole.is_empty else None}
    return back, lines, info


def build(back, lines):
    """[(slot, name, mesh)]: white back (slot 1) and raised black lines (slot 2)."""
    import trimesh

    from cad.name_tag import drop_slivers, extrude

    white = extrude(back, 0, BACK_T)
    black = extrude(lines, BACK_T, BACK_T + LINE_T)
    out = []
    for slot, name, m in ((1, "white back", white), (2, "black lines", black)):
        m = drop_slivers(m) if isinstance(m, trimesh.Trimesh) else m
        out.append((slot, name, m))
    return out


def preview(back, lines, path: Path, title: str = ""):
    """Flat 'photo' of the ornament on a wood table (like the mock-up sheets)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from cad.coloring_ornaments import _patches

    x0, y0, x1, y1 = back.bounds
    pad = 10
    fig = plt.figure(figsize=((x1 - x0 + 2 * pad) / 18, (y1 - y0 + 2 * pad) / 18), dpi=120)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(x0 - pad, x1 + pad)
    ax.set_ylim(y0 - pad, y1 + pad)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.add_patch(plt.Rectangle((x0 - pad, y0 - pad), x1 - x0 + 2 * pad, y1 - y0 + 2 * pad, color="#B98A5A"))
    for p in _patches(translate(back, 1.2, -1.2), color="black", alpha=0.25, lw=0):
        ax.add_patch(p)
    for p in _patches(back, color=WHITE, lw=0):
        ax.add_patch(p)
    for p in _patches(lines, color=BLACK, lw=0):
        ax.add_patch(p)
    if title:
        ax.text(x0 - pad + 2, y1 + pad - 4, title, fontsize=8, color="white")
    fig.savefig(path)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    from meshy3d import bambu3mf

    ap = argparse.ArgumentParser(description="Trace ornament art into a printable color-in ornament")
    ap.add_argument("image", type=Path)
    ap.add_argument("name")
    ap.add_argument("--body", type=float, default=BODY_D)
    ap.add_argument("--out", type=Path, default=Path("output/cad-ornaments"))
    args = ap.parse_args(argv)
    back, lines, info = trace(args.image, args.body)
    info.update(check(back, lines))
    out = args.out / args.name
    out.mkdir(parents=True, exist_ok=True)
    parts = build(back, lines)
    info["watertight"] = {n: bool(m.is_watertight) for _, n, m in parts}
    bambu3mf.write([bambu3mf.Part(n, m, s) for s, n, m in parts], [WHITE, BLACK], out / f"{args.name}.3mf",
                   name=args.name)
    preview(back, lines, out / f"{args.name}-preview.png")
    (out / "report.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
