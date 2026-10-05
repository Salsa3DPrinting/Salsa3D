"""Put a painted multi-color figure (e.g. Meshy's multi-color 3MF) on a plain CAD base.

The figure keeps its per-triangle paint; the base is its own part on an extra filament slot.
Total height = base + figure. The figure stands exactly on the base top (touching, not
overlapping, so no triangle is claimed by two filaments).

Gaps: AI figures don't always end flat (e.g. a rifle butt a few mm above the boots). Any
underside within `fill_mm` of the figure's bottom that would float over the base gets a small
pedestal of base material up to it, so nothing prints in mid-air.

Run: python -m cad.figure_base FIGURE.3mf --total-mm 150 [--base-mm 8] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import shapely.geometry as sg
import trimesh
from shapely.ops import unary_union

from meshy3d import bambu3mf, printprep

BASE_COLOR = "#9A9EA3"


def slab(poly: sg.Polygon, height: float, chamfer: float) -> trimesh.Trimesh:
    """Convex slab with a chamfered top edge (poly must be convex)."""
    bottom = np.asarray(poly.exterior.coords)[:-1]
    top = np.asarray(poly.buffer(-chamfer, join_style="round").exterior.coords)[:-1]
    pts = np.vstack([np.c_[bottom, np.zeros(len(bottom))], np.c_[bottom, np.full(len(bottom), height - chamfer)],
                     np.c_[top, np.full(len(top), height)]])
    return trimesh.convex.convex_hull(pts)


def underside_gaps(fig: trimesh.Trimesh, cell: float, fill_mm: float) -> list[tuple[sg.Polygon, float]]:
    """Separate features whose underside floats between ~0 and fill_mm above the figure's bottom.

    Only patches that don't touch the part resting on the base count (so a rifle butt hanging a few
    mm up is filled, the curled-up edge of a rounded boot sole is not).
    Returns (patch polygon, lowest underside height above the bottom) per patch.
    """
    lo, hi = fig.bounds
    xs = np.arange(lo[0] + cell / 2, hi[0], cell)
    ys = np.arange(lo[1] + cell / 2, hi[1], cell)
    gx, gy = np.meshgrid(xs, ys)
    origins = np.c_[gx.ravel(), gy.ravel(), np.full(gx.size, lo[2] - 1.0)]
    _, ray_idx, locs = fig.ray.intersects_id(origins, np.tile([0, 0, 1.0], (len(origins), 1)),
                                             multiple_hits=False, return_locations=True)
    height = np.full(len(origins), np.nan)
    height[ray_idx] = locs[:, 2] - lo[2]
    floating = (height > 0.15) & (height <= fill_mm)
    resting = height <= 0.15

    def cells_of(mask):
        return [sg.box(x - cell / 2, y - cell / 2, x + cell / 2, y + cell / 2)
                for (x, y, _), f in zip(origins, mask) if f]

    cells = cells_of(floating)
    if not cells:
        return []
    contact = unary_union(cells_of(resting)).buffer(cell * 0.6)
    merged = unary_union(cells)
    patches = []
    for poly in getattr(merged, "geoms", [merged]):
        if poly.intersects(contact):
            continue
        inside = [h for (x, y, _), h, f in zip(origins, height, floating) if f and poly.contains(sg.Point(x, y))]
        patches.append((poly, float(min(inside))))
    return patches


def build(figure_3mf: Path, total_mm: float, base_mm: float = 8.0, margin_mm: float = 6.0,
          corner_mm: float = 4.0, chamfer_mm: float = 1.0, fill_mm: float = 6.0, cell_mm: float = 0.5):
    fig, paint, palette = bambu3mf.read_painted(figure_3mf)
    fig = trimesh.Trimesh(fig.vertices.copy(), fig.faces.copy(), process=False)
    fig_h = total_mm - base_mm
    fig.apply_scale(fig_h / fig.extents[2])
    lo, hi = fig.bounds
    fig.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, base_mm - lo[2]])

    lo, hi = fig.bounds
    outline = sg.box(lo[0] - margin_mm, lo[1] - margin_mm, hi[0] + margin_mm, hi[1] + margin_mm)
    outline = outline.buffer(-corner_mm, join_style="mitre").buffer(corner_mm, quad_segs=16)
    base = slab(outline, base_mm, chamfer_mm)

    pedestals = []
    for patch, h in underside_gaps(fig, cell_mm, fill_mm):
        # Shrunk slightly so the pedestal hides beneath the feature.
        shape = patch.buffer(-0.2)
        if shape.is_empty or h <= 0.15:
            continue
        for poly in getattr(shape, "geoms", [shape]):
            # From inside the base (z=0.5, fuses with it) up to exactly the floating feature's lowest point.
            ped = trimesh.creation.extrude_polygon(poly.simplify(0.05), base_mm + h - 0.5)
            ped.apply_translation([0, 0, 0.5])
            pedestals.append((ped, round(h, 2), round(poly.area, 1)))
    if pedestals:
        base = trimesh.boolean.union([base] + [p for p, _, _ in pedestals], engine="manifold")

    base_slot = len(palette) + 1
    parts = [bambu3mf.Part("figure", fig, 1, paint=paint), bambu3mf.Part("base", base, base_slot)]
    info = {
        "figure_height_mm": round(float(fig.extents[2]), 2),
        "total_height_mm": round(float(max(fig.bounds[1][2], base.bounds[1][2])), 2),
        "base_footprint_mm": [round(float(v), 1) for v in base.extents[:2]],
        "base_watertight": bool(base.is_watertight),
        "pedestals": [{"gap_mm": h, "area_mm2": a} for _, h, a in pedestals],
        "palette": palette + [BASE_COLOR],
        "base_slot": base_slot,
    }
    return parts, info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Put a painted figure 3MF on a plain CAD base")
    ap.add_argument("figure", type=Path, help="Painted figure 3MF (e.g. Meshy multicolor output)")
    ap.add_argument("--total-mm", type=float, required=True, help="Overall height including the base")
    ap.add_argument("--base-mm", type=float, default=8.0)
    ap.add_argument("--margin-mm", type=float, default=6.0, help="Base overhang around the figure")
    ap.add_argument("--max-slots", type=int, default=8, help="Filament slots available (AMS)")
    ap.add_argument("--single-color-stl", type=Path, help="Watertight STL of the same figure for a 1-color version")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    parts, info = build(args.figure, args.total_mm, args.base_mm, args.margin_mm)
    if len(info["palette"]) > args.max_slots:
        raise SystemExit(f"figure colors + base = {len(info['palette'])} filaments, more than --max-slots "
                         f"{args.max_slots}; make the figure with fewer colors")
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    path = bambu3mf.write(parts, info["palette"], out / "figure-on-base.3mf", name=args.figure.stem)

    fig, base = parts[0].mesh, parts[1].mesh
    codes = np.array([printprep.BAMBU_PAINT_CODES.get(c, 1) for c in parts[0].paint])
    rgb = printprep.hex_to_rgb(info["palette"])
    colors = np.vstack([rgb[codes - 1], np.tile(rgb[info["base_slot"] - 1], (len(base.faces), 1))])
    tri = np.concatenate([fig.triangles, base.triangles])
    printprep.render_colored_faces(tri, colors, out / "figure-on-base-colors.png", "Figure on base, filament colors")

    if args.single_color_stl:
        solid = printprep.load_mesh(args.single_color_stl)
        solid.apply_scale((fig.extents[2] + 0.2) / solid.extents[2])  # +0.2 for the sink below
        lo, hi = solid.bounds
        flo, fhi = fig.bounds
        # Sunk 0.2 mm so the single-color print is one fused body (the 3MF keeps an exact touch instead).
        solid.apply_translation([(flo[0] + fhi[0] - lo[0] - hi[0]) / 2, (flo[1] + fhi[1] - lo[1] - hi[1]) / 2,
                                 flo[2] - lo[2] - 0.2])
        combined = trimesh.boolean.union([solid, base], engine="manifold")
        combined.export(out / "figure-on-base-single-color.stl")
        printprep.render_preview(combined, out / "figure-on-base-preview.png")
        info["single_color"] = printprep.report(combined).to_dict()
    info["file"] = str(path)
    (out / "report.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
