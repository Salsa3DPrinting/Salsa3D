"""Minecraft-style round name tag (grass-block look), built from pixels.

Layout (mm, tag lies flat, top face +Z, "up" on the tag is +Y):
- z 0-1.4   dirt-brown disc (the body)
- z 1.0-1.4 flush inlays in the top of the body: grass cap with pixel drips, darker grass/dirt speckles
- z 1.4-2.0 raised: pixel-stepped black rim, white pixel-font text, creeper face
- a through hole near the top for a cable tie

Run: python -m cad.name_tag --line1 "M. Rodriguez" --line2 "Room 14" [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import shapely.geometry as sg
import trimesh
from shapely.affinity import translate
from shapely.ops import unary_union

from cad.pixelfont import text_shape, text_width_px
from meshy3d import bambu3mf, printprep

PALETTE = ["#8A5A3B", "#5C3D29", "#5DA130", "#3E7A1F", "#F4F4F4", "#1C1C1C"]
DIRT, DARK_DIRT, GRASS, DARK_GRASS, WHITE, BLACK = range(1, 7)

DIAMETER = 63.5            # 2.5 in
BODY_T = 1.4               # body thickness; raised art brings the total to 2.0
INLAY_T = 0.4              # colored top layers of the body
RAISED_T = 0.6
HOLE_D, HOLE_Y = 5.2, 23.5  # fits cable ties up to ~4.8 mm wide
RIM_CELL, RIM_IN, RIM_OUT = 1.25, 29.4, 31.4
GRID = 2.0                 # texture pixel size
GRASS_LINE, MAX_DRIP = 15.0, 2  # grass above this y, with drips of 0-2 pixels
SPECKLE = 0.2              # share of texture pixels that get the darker shade
LINE1_PX, LINE1_TOP = 0.8, 9.0
LINE2_PX, LINE2_TOP = 1.0, 0.5
CREEPER_PX, CREEPER_TOP = 1.1, -9.0
CREEPER = ["........", "........", ".##..##.", ".##..##.", "...##...", "..####..", "..####..", "..#..#.."]
SEED = 14


def extrude(shape, z0: float, z1: float) -> trimesh.Trimesh:
    """Extrude a shapely shape into a solid between z0 and z1.

    Uses manifold3d's 2D engine: pixel art has squares and holes touching only at corners, which
    is valid in shapely but breaks ear-clipping triangulation; manifold resolves it into a clean solid.
    """
    import manifold3d as m3
    from shapely.geometry.polygon import orient

    contours = []
    for p in getattr(shape, "geoms", [shape]):
        if p.is_empty or p.area <= 1e-9:
            continue
        p = orient(p, 1.0)  # CCW outside, CW holes -> positive fill rule
        contours.append(np.asarray(p.exterior.coords)[:-1])
        contours += [np.asarray(r.coords)[:-1] for r in p.interiors]
    solid = m3.Manifold.extrude(m3.CrossSection(contours, m3.FillRule.Positive), z1 - z0).translate((0, 0, z0))
    mesh = solid.to_mesh()
    return trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=False)


def drop_slivers(mesh: trimesh.Trimesh, min_mm3: float = 1e-3) -> trimesh.Trimesh:
    """Remove zero-volume fragments that boolean ops can leave where many edges meet."""
    pieces = [p for p in mesh.split(only_watertight=False) if abs(p.volume) >= min_mm3]
    return trimesh.util.concatenate(pieces) if len(pieces) > 1 else pieces[0]


def grid_cells(cell: float, radius: float):
    n = int(np.ceil(radius / cell)) + 1
    for i in range(-n, n):
        for j in range(-n, n):
            yield i, j, sg.box(i * cell, j * cell, (i + 1) * cell, (j + 1) * cell)


def build(line1: str, line2: str):
    rng = random.Random(SEED)
    r = DIAMETER / 2
    disc = sg.Point(0, 0).buffer(r, quad_segs=64)
    hole = sg.Point(0, HOLE_Y).buffer(HOLE_D / 2, quad_segs=32)

    # Grass cap: pixel columns, each dripping 0..MAX_DRIP pixels below the grass line.
    grass_cells, dirt_cells = [], []
    for i, j, cell in grid_cells(GRID, r):
        if not cell.intersects(disc):
            continue
        drip = rng.randint(0, MAX_DRIP) if j * GRID < GRASS_LINE else 0
        is_grass = (j + 1) * GRID > GRASS_LINE - drip * GRID
        (grass_cells if is_grass else dirt_cells).append(cell)
    grass = unary_union(grass_cells).intersection(disc)
    dark_grass = unary_union([c for c in grass_cells if rng.random() < SPECKLE]).intersection(grass)
    dark_dirt = unary_union([c for c in dirt_cells if rng.random() < SPECKLE]).intersection(disc).difference(grass)
    grass = grass.difference(dark_grass)

    # Raised art.
    rim = unary_union([c for _, _, c in grid_cells(RIM_CELL, r)
                       if RIM_IN <= c.centroid.distance(sg.Point(0, 0)) <= RIM_OUT + RIM_CELL])
    rim = rim.intersection(disc).difference(sg.Point(0, 0).buffer(RIM_IN - RIM_CELL / 2, quad_segs=64))
    lines = [(text_shape(line1, LINE1_PX, 0, LINE1_TOP), LINE1_PX), (text_shape(line2, LINE2_PX, 0, LINE2_TOP), LINE2_PX)]
    text = unary_union([t for t, _ in lines])
    # Minecraft-style drop shadow: one pixel down-right, flush in the top of the body under the raised text.
    shadow = unary_union([unary_union([t, translate(t, px, -px)]) for t, px in lines])
    x0 = -len(CREEPER[0]) * CREEPER_PX / 2
    creeper_cells = {"#": [], ".": []}
    for row, line in enumerate(CREEPER):
        for col, v in enumerate(line):
            creeper_cells[v].append(sg.box(x0 + col * CREEPER_PX, CREEPER_TOP - (row + 1) * CREEPER_PX,
                                           x0 + (col + 1) * CREEPER_PX, CREEPER_TOP - row * CREEPER_PX))
    creeper_face = unary_union(creeper_cells["."])
    creeper_eyes = unary_union(creeper_cells["#"])

    inlay_z0, top = BODY_T - INLAY_T, BODY_T
    body = disc.difference(hole)
    grass, dark_grass, dark_dirt = (g.difference(shadow) for g in (grass, dark_grass, dark_dirt))
    inlays = unary_union([grass, dark_grass, dark_dirt, shadow])
    parts_2d = [
        ("body", DIRT, None, body),  # handled specially below (full-depth with top inlays cut out)
        ("grass", GRASS, (inlay_z0, top), grass.difference(hole)),
        ("dark grass", DARK_GRASS, (inlay_z0, top), dark_grass.difference(hole)),
        ("dark dirt", DARK_DIRT, (inlay_z0, top), dark_dirt.difference(hole)),
        ("text shadow", BLACK, (inlay_z0, top), shadow.difference(hole)),
        ("rim", BLACK, (top, top + RAISED_T), unary_union([rim, creeper_eyes]).difference(hole)),
        ("text", WHITE, (top, top + RAISED_T), text.difference(hole)),
        ("creeper", GRASS, (top, top + RAISED_T), creeper_face),
    ]
    lower = extrude(body, 0, inlay_z0)
    upper = extrude(body.difference(inlays), inlay_z0, top)
    body_mesh = trimesh.boolean.union([lower, upper], engine="manifold")

    by_slot: dict[int, list[trimesh.Trimesh]] = {DIRT: [body_mesh]}
    names = {DIRT: "dirt body", DARK_DIRT: "dirt speckles", GRASS: "grass + creeper", DARK_GRASS: "grass speckles",
             WHITE: "text", BLACK: "rim, creeper face, text shadow"}
    for _, slot, z, shape in parts_2d[1:]:
        if shape.is_empty:
            continue
        by_slot.setdefault(slot, []).append(extrude(shape, *z))
    parts = [bambu3mf.Part(names[s], drop_slivers(trimesh.boolean.union(ms, engine="manifold") if len(ms) > 1
                                                  else ms[0]), s)
             for s, ms in sorted(by_slot.items())]

    layout = {
        "line1_mm": [round(text_width_px(line1) * LINE1_PX, 1), round(7 * LINE1_PX, 1)],
        "line2_mm": [round(text_width_px(line2) * LINE2_PX, 1), round(7 * LINE2_PX, 1)],
        "text_inside_rim": bool(sg.Point(0, 0).buffer(RIM_IN - RIM_CELL).contains(text)),
        "creeper_inside_rim": bool(sg.Point(0, 0).buffer(RIM_IN - RIM_CELL).contains(creeper_face)),
        "text_clear_of_hole": not text.intersects(hole.buffer(1.0)),
        "text_clear_of_creeper": not text.buffer(0.5).intersects(unary_union([creeper_face, creeper_eyes])),
        "hole_wall_to_edge_mm": round(r - HOLE_Y - HOLE_D / 2, 2),
    }
    return parts, layout


def check(parts) -> dict:
    out = {"parts": {}, "overlaps_mm3": {}}
    for p in parts:
        out["parts"][p.name] = {"slot": p.filament, "watertight": bool(p.mesh.is_watertight),
                                "volume_mm3": round(float(p.mesh.volume), 1)}
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            inter = trimesh.boolean.intersection([a.mesh, b.mesh], engine="manifold")
            with np.errstate(divide="ignore", invalid="ignore"):
                vol = float(inter.volume) if len(inter.faces) else 0.0
            if vol > 1e-3:
                out["overlaps_mm3"][f"{a.name} / {b.name}"] = round(vol, 4)
    allm = trimesh.util.concatenate([p.mesh for p in parts])
    out["extents_mm"] = [round(float(v), 3) for v in allm.extents]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Minecraft-style round name tag")
    ap.add_argument("--line1", default="M. Rodriguez")
    ap.add_argument("--line2", default="Room 14")
    ap.add_argument("--out", type=Path, default=Path("output/cad-name-tag"))
    args = ap.parse_args(argv)
    parts, layout = build(args.line1, args.line2)
    report = {"layout": layout, **check(parts)}
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    bambu3mf.write(parts, PALETTE, out / "name-tag.3mf", name=f"tag {args.line1}")
    combined = drop_slivers(trimesh.boolean.union([p.mesh for p in parts], engine="manifold"))
    combined.export(out / "name-tag-single-color.stl")
    report["single_color"] = printprep.report(combined).to_dict()
    # Color render: stand the tag up so its face looks toward the renderer's camera (-Y).
    stand = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
    tri = np.concatenate([p.mesh.copy().apply_transform(stand).triangles for p in parts])
    rgb = printprep.hex_to_rgb(PALETTE)
    colors = np.concatenate([np.tile(rgb[p.filament - 1], (len(p.mesh.faces), 1)) for p in parts])
    printprep.render_colored_faces(tri, colors, out / "name-tag-colors.png", f"{args.line1} / {args.line2}",
                                   views=((0, "Face"), (-30, "Angled")), px_per_mm=12)
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
