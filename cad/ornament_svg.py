"""Vectorize the ornament concept art (PNG) into SVGs for modeling in Fusion 360.

The black areas of the art become closed filled paths, then the drawing is made colorable: line
parts thinner than MIN_LINE are thickened (so they print), and any white space a MARKER_D marker tip
can't get into is filled black. The result is checked against both rules (report.json).
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

BODY_D = 100.0
SOLDIER_H = 80.0             # fits inside a 100 mm ball ornament later
MARKER_D = 1.0               # every white space must hold a circle this size (a 1 mm marker tip)
MIN_LINE = 1.6               # thinnest black line (4 passes of a 0.4 mm nozzle)
LINE_TOL = 0.1               # traced edges wobble a little; lines count as thin only below MIN_LINE - this
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


def frame(png: Path, name: str):
    """Trace the art (pixel units, y up) and work out the mm frame: (black, whole, hole, k, x0, y0)."""
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
    return black, whole, hole, k, x0, y0


def _mm(g, k: float, x0: float, y0: float, up: int = 1):
    return translate(scale(g, k / up, k / up, origin=(0, 0)), -x0 * k, -y0 * k).simplify(SIMPLIFY_MM)


def vectorize(png: Path, name: str):
    black, whole, hole, k, x0, y0 = frame(png, name)
    lines = _mm(black, k, x0, y0)
    lines = unary_union([g for g in getattr(lines, "geoms", [lines]) if g.area >= MIN_AREA_MM2])
    back = _mm(whole, k, x0, y0).difference(_mm(hole, k, x0, y0))
    bx0, by0, bx1, by1 = whole.bounds
    return back, lines, (bx1 - bx0) * k, (by1 - by0) * k


def _opening(g, d: float):
    return g.buffer(-d / 2, quad_segs=8).buffer(d / 2, quad_segs=8)


def make_colorable(back, lines, marker: float = MARKER_D, min_line: float = MIN_LINE):
    """Thicken too-thin line parts and fill white spaces a marker tip can't enter. Returns (back, lines, info).

    Lines may grow past the outer edge (e.g. a thin hanging ring or rim), so the back grows with them.
    """
    thin = lines.difference(_opening(lines, min_line - LINE_TOL)).buffer(0)
    grown = []
    for g in getattr(thin, "geoms", [thin]):
        t = 2 * g.area / g.length if g.length else 0   # stroke width estimate of this thin bit
        if g.area < 0.05 or t < 0.3:
            continue                                    # corner crumbs, not real thin strokes
        grown.append(g.buffer(max(0.1, (min_line - t) / 2 + 0.05), quad_segs=6))
    lines = unary_union([lines, *grown]).simplify(SIMPLIFY_MM)
    back = unary_union([back, lines]).simplify(SIMPLIFY_MM)
    lines = lines.intersection(back)
    regions = [g for g in getattr(back.difference(lines), "geoms", [back.difference(lines)]) if g.area > 1e-4]
    filled = [g for g in regions if g.buffer(-marker / 2).is_empty]
    lines = unary_union([lines, *[g.buffer(0.01) for g in filled]]).intersection(back)
    return back, lines, {"thin_line_parts_thickened": len(grown), "spaces_filled": len(filled)}


def thin_skeleton(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen thinning of a boolean image to 1 px wide centerlines."""
    img = np.pad(mask.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            p = [np.roll(np.roll(img, -dy, 0), -dx, 1) for dy, dx in
                 ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))]   # P2..P9
            b = sum(p)
            a = sum(((p[i] == 0) & (p[(i + 1) % 8] == 1)).astype(np.uint8) for i in range(8))
            if step == 0:
                c = (p[0] * p[2] * p[4] == 0) & (p[2] * p[4] * p[6] == 0)
            else:
                c = (p[0] * p[2] * p[6] == 0) & (p[0] * p[4] * p[6] == 0)
            kill = (img == 1) & (b >= 2) & (b <= 6) & (a == 1) & c
            if kill.any():
                img[kill] = 0
                changed = True
        if not changed:
            return img[1:-1, 1:-1].astype(bool)


def _circle_fit(ys: np.ndarray, xs: np.ndarray):
    """Least-squares circle through pixels: (cy, cx, r, rms)."""
    A = np.c_[2 * xs, 2 * ys, np.ones(len(xs))]
    c, *_ = np.linalg.lstsq(A, xs**2 + ys**2, rcond=None)
    cx, cy = c[0], c[1]
    r = np.sqrt(c[2] + cx**2 + cy**2)
    rms = np.sqrt(np.mean((np.hypot(xs - cx, ys - cy) - r) ** 2))
    return cy, cx, r, rms


def _draw_arc(mask: np.ndarray, cy: float, cx: float, r: float, a0: float, a1: float) -> None:
    n = max(16, int(abs(a1 - a0) * r * 2))
    t = np.linspace(a0, a1, n)
    yy, xx = np.round(cy + r * np.sin(t)).astype(int), np.round(cx + r * np.cos(t)).astype(int)
    ok = (yy >= 0) & (yy < mask.shape[0]) & (xx >= 0) & (xx < mask.shape[1])
    mask[yy[ok], xx[ok]] = True


def find_circles(skel: np.ndarray, mm_per_px: float, r_mm=(1.5, 3.6), min_cover: float = 0.45,
                 step_mm: float = 0.1):
    """Circles drawn as outlines (polka dots, part-dots cut by an edge): a circular Hough search on the
    centerlines. Returns [(cy, cx, r)] in pixels, strongest first, without near-duplicates."""
    from scipy import ndimage
    from scipy.signal import fftconvolve

    f = 4                                                          # search on a 4x coarser grid (fast)
    small = ndimage.maximum_filter(skel.astype(np.uint8), size=f)[::f, ::f].astype(float)
    found = []
    for r_mm_i in np.arange(r_mm[0], r_mm[1] + 1e-9, step_mm):
        r = r_mm_i / mm_per_px / f
        n = int(np.ceil(r)) + 2
        yy, xx = np.mgrid[-n:n + 1, -n:n + 1]
        ring = (np.abs(np.hypot(yy, xx) - r) <= 0.75).astype(float)
        acc = fftconvolve(small, ring, mode="same") / ring.sum()
        peaks = (acc == ndimage.maximum_filter(acc, size=int(2 * r))) & (acc >= min_cover)
        for cy, cx in zip(*np.nonzero(peaks)):
            found.append((acc[cy, cx], cy * f + f / 2, cx * f + f / 2, r * f))
    found.sort(reverse=True)
    keep = []
    for score, cy, cx, r in found:
        if all(np.hypot(cy - ky, cx - kx) > 0.6 * max(r, kr) for ky, kx, kr in keep):
            keep.append((cy, cx, r))
    return keep


def perfect_circles(skel: np.ndarray, mm_per_px: float, end_keep_mm: float = 0.8):
    """Swap the centerlines of outlined dots (whole or cut by an edge) for exact circles/arcs.

    The arc is redrawn only over the angles where the art has it; near the arc's ends (where it meets
    an edge or the ribbon) the original pixels are left alone so those lines stay connected."""
    out = skel.copy()
    circles = find_circles(skel, mm_per_px)
    radii = []
    band = 0.5 / mm_per_px
    yy_all, xx_all = np.nonzero(skel)
    for cy, cx, r in circles:
        # refine with a least-squares fit on the centerline pixels near this ring
        near = np.abs(np.hypot(yy_all - cy, xx_all - cx) - r) <= band
        if near.sum() < 20:
            continue
        cy, cx, r, _ = _circle_fit(yy_all[near].astype(float), xx_all[near].astype(float))
        d = np.hypot(yy_all - cy, xx_all - cx)
        on = np.abs(d - r) <= band
        ang = np.arctan2(yy_all[on] - cy, xx_all[on] - cx)
        bins = np.zeros(360, bool)
        bins[(np.degrees(ang).astype(int) + 360) % 360] = True
        bins = np.convolve(np.r_[bins, bins, bins].astype(int), np.ones(5), "same")[360:720] > 0   # close tiny gaps
        if bins.all():
            spans = [(0.0, 2 * np.pi)]
            ends = []
        else:
            start = int(np.argmin(bins))                          # a gap: walk the circle from there
            spans, ends, k = [], [], 0
            order = [(start + t) % 360 for t in range(360)]
            while k < 360:
                if bins[order[k]]:
                    a = k
                    while k < 360 and bins[order[k]]:
                        k += 1
                    a0, a1 = np.radians(order[a]), np.radians(order[a]) + np.radians(k - a)
                    spans.append((a0, a1))
                    ends += [a0, a1]
                k += 1
        keep_ang = end_keep_mm / (r * mm_per_px)                   # radians of original kept at arc ends
        for a0, a1 in spans:
            sel = on.copy()
            a = np.arctan2(yy_all - cy, xx_all - cx)
            rel = (a - a0) % (2 * np.pi)
            inside = rel <= (a1 - a0)
            if ends:
                inside &= (rel > keep_ang) & (rel < (a1 - a0) - keep_ang)
            sel &= inside
            out[yy_all[sel], xx_all[sel]] = False
            _draw_arc(out, cy, cx, r, a0, a1)
        radii.append(r)
    return out, radii


def restroke(png: Path, name: str, target: float, solid_mm: float = 3.4, up: int = 3,
             perfect_dots: bool = False, solid_ring: bool = False):
    """Redraw the art's strokes at an even `target` width from their centerlines (raster), keeping parts
    thicker than `solid_mm` (filled dots, a heavy rim) solid. Returns (back, lines, w, h, info).

    perfect_dots: round solid dots become exact outlined circles (colorable), and nearly circular arcs
    (dots cut by an edge) become exact arcs. solid_ring: the hanging ring is filled solid black."""
    from scipy import ndimage

    src = Image.open(png).convert("L")
    big = src.resize((src.width * up, src.height * up), Image.BICUBIC)
    black = np.asarray(big, dtype=float) / 255.0 < 0.5
    back, _, w, h = vectorize(png, name)
    _, _, _, k, x0, y0 = frame(png, name)
    mm_per_px = k / up
    dist = ndimage.distance_transform_edt(black) * mm_per_px          # half-thickness at each black px
    core = dist > solid_mm / 2
    solid = ndimage.binary_dilation(core, iterations=int(np.ceil(solid_mm / 2 / mm_per_px))) & black
    # Only roundish solid shapes stay solid (filled dots); long thick bits (e.g. a heavier rim) get restroked.
    lab, _ = ndimage.label(solid)
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        hh, ww = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        fill = (lab[sl] == i).sum() / (hh * ww)
        if max(hh, ww) / max(1, min(hh, ww)) > 1.8 or fill < 0.5:
            solid[lab == i] = False
    skel = thin_skeleton(black & ~ndimage.binary_erosion(solid, iterations=2))
    info = {}
    if perfect_dots:
        skel, radii = perfect_circles(skel, mm_per_px)
        info["arcs_made_round"] = len(radii)
        # Solid dots become outlined circles the same size as the art's outlined dots (so they all match),
        # shrunk where a full-size circle would run into another line.
        r_dot = float(np.median(radii)) if radii else None
        lab, n_dots = ndimage.label(solid)
        others = ndimage.distance_transform_edt(~skel)                # px to the nearest other centerline
        gap_px = (target + 1.0) / mm_per_px                         # a stroke plus a 1 mm marker space
        for i in range(1, n_dots + 1):
            ys, xs = np.nonzero(lab == i)
            cy, cx = ys.mean(), xs.mean()
            r = r_dot if r_dot else np.sqrt(len(ys) / np.pi) - target / 2 / mm_per_px
            r = min(r, others[round(cy), round(cx)] - gap_px)
            if r * mm_per_px >= 0.5 + target / 2:                   # still has a colorable middle
                _draw_arc(skel, cy, cx, r, 0, 2 * np.pi)
        solid[:] = False
        info["solid_dots_made_outlines"] = int(n_dots)
    strokes = ndimage.distance_transform_edt(~skel) * mm_per_px <= target / 2
    new = solid | strokes
    img = np.where(new, 0.0, 1.0)
    shapes = black_shapes(img)
    lines = _mm(shapes, k, x0, y0, up)
    lines = unary_union([g for g in getattr(lines, "geoms", [lines]) if g.area >= MIN_AREA_MM2])
    # The rim is thinner now: trim the back to the new rim's outer edge, and find the hanging hole again.
    parts = list(getattr(lines, "geoms", [lines]))
    whole = sg.Polygon(max(parts, key=lambda g: sg.Polygon(g.exterior).area).exterior)
    if name == "soldier":
        whole = unary_union([sg.Polygon(g.exterior) for g in parts])
    _, by0, _, by1 = whole.bounds
    inside = whole.difference(lines)
    # the hole is the roundest white space up top (the ring's white band around it is a C or an annulus)
    holes = [g for g in getattr(inside, "geoms", [inside])
             if name != "soldier" and g.centroid.y > by1 - 0.15 * (by1 - by0) and g.area < 0.01 * whole.area
             and not g.interiors and 4 * np.pi * g.area / g.length**2 > 0.7]
    hole = max(holes, key=lambda g: 4 * np.pi * g.area / g.length**2) if holes else sg.Polygon()
    back = whole.difference(hole)
    lines = lines.intersection(back)
    if solid_ring and not hole.is_empty:
        # fill every white space in the ring around the hanging hole (and the wedge under it) black
        hole_r = np.sqrt(hole.area / np.pi)
        near = hole.centroid.buffer(hole_r * 2.6)
        white = back.difference(lines)
        ring_white = [g for g in getattr(white, "geoms", [white]) if g.within(near.buffer(0.5))]
        lines = unary_union([lines, *[g.buffer(0.01) for g in ring_white]]).intersection(back)
        info["ring_spaces_filled"] = len(ring_white)
    return back, lines, w, h, info


def verify(back, lines, marker: float = MARKER_D, min_line: float = MIN_LINE) -> dict:
    """Check the final drawing: no white space too small for the marker, no line thinner than min_line."""
    white = back.difference(lines)
    regions = [g for g in getattr(white, "geoms", [white]) if g.area > 1e-4]
    too_small = [g for g in regions if g.buffer(-marker / 2 + 1e-3).is_empty]
    hard_to_reach = [g for g in regions
                     if _opening(g, marker).area / g.area < 0.9]
    thin = lines.difference(_opening(lines, min_line - LINE_TOL))
    # real thin strokes, not the crumbs an opening shaves off sharp outside corners (< 0.3 mm wide)
    thin_parts = [g for g in getattr(thin, "geoms", [thin]) if g.area > 0.05 and 2 * g.area / g.length >= 0.3]
    return {"white_spaces": len(regions), "spaces_too_small_for_marker": len(too_small),
            "spaces_with_corners_out_of_reach": len(hard_to_reach),
            "smallest_space_mm2": round(min(g.area for g in regions), 2) if regions else None,
            "line_parts_thinner_than_min": len(thin_parts)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ornament concept art -> SVG for Fusion 360")
    ap.add_argument("--src", type=Path, default=Path("output/ornament-art"))
    ap.add_argument("--out", type=Path, default=Path("output/ornament-svg"))
    ap.add_argument("--line", type=float, default=None,
                    help="make strokes this wide (mm); default keeps the traced width (at least MIN_LINE)")
    ap.add_argument("--marker", type=float, default=MARKER_D)
    ap.add_argument("--perfect-dots", action="store_true", help="exact outlined circles for polka dots (with --line)")
    ap.add_argument("--solid-ring", action="store_true", help="fill the hanging ring solid black (with --line)")
    ap.add_argument("names", nargs="*", help="only these designs (default: all)")
    args = ap.parse_args(argv)
    min_line = args.line or MIN_LINE
    args.out.mkdir(parents=True, exist_ok=True)
    report = {}
    for png in sorted(args.src.glob("*/*/gen-1.png")):
        name = png.parts[-3]
        if args.names and name not in args.names:
            continue
        slim_info = {}
        if args.line:
            back, lines, w, h, extra = restroke(png, name, args.line, perfect_dots=args.perfect_dots,
                                                solid_ring=args.solid_ring)
            slim_info = {"restroked_mm": args.line, **extra}
        else:
            back, lines, w, h = vectorize(png, name)
        fix = {"thin_line_parts_thickened": 0, "spaces_filled": 0, "passes": 0}
        for _ in range(6):                        # fixing can create new slivers; repeat until clean
            back, lines, f = make_colorable(back, lines, args.marker, min_line)   # simplifies before filling
            fix = {k: fix[k] + f.get(k, 0) for k in fix} | {"passes": fix["passes"] + 1}
            v = verify(back, lines, args.marker, min_line)
            if not v["spaces_too_small_for_marker"] and not v["line_parts_thinner_than_min"]:
                break
        (args.out / f"{name}-lines.svg").write_text(svg([("lines", lines, "#000000")], w, h))
        (args.out / f"{name}-back.svg").write_text(svg([("back", back, "#000000")], w, h))
        (args.out / f"{name}.svg").write_text(svg([("back", back, "#DDDDDD"), ("lines", lines, "#000000")], w, h))
        n_pts = sum(len(r.coords) for r in _rings(lines))
        report[name] = {"size_mm": [round(w, 1), round(h, 1)], "min_line_mm": min_line, "marker_mm": args.marker,
                        **slim_info, **fix, **verify(back, lines, args.marker, min_line),
                        "line_profiles": len(getattr(lines, "geoms", [lines])), "points": n_pts}
    (args.out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
