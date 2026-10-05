"""Parametric model of the VENTURI aseptic isolator miniature, built from simple solids.

Coordinates: mm, X = width (centered), Y = depth (front face toward -Y), Z = up, base on z = 0.
Every colored feature is its own part on a filament slot, so the multi-color print comes from
geometry rather than a texture.

Where the numbers come from (no physical measurements were available):
- Overall height 203.2 mm = the user's "about 8 inches".
- Width, depth and the side profile (toe kick, counter lip, opening depth, header overhang) were
  measured on the Meshy mesh of the same object (output/20261005-122603-edited-1/model.stl).
- Front layout (knob heights, label, panels, handles, baffle lines) was measured on the cleaned
  straight-on photo, mapped to mm with the opening as the reference.
Change the constants below to correct any of them.

Run: python -m cad.isolator [--out DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import shapely.geometry as sg
import trimesh
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextPath

from meshy3d import bambu3mf, printprep

# --- Filament slots (8-slot AMS setup) ---------------------------------------
PALETTE = [
    "#2E3335",  # 1 charcoal: body, sash, baffle lines, handles, outlets
    "#F2F2EE",  # 2 white: interior liner, label plate
    "#C62828",  # 3 red: label letters, red knobs
    "#F2C500",  # 4 yellow knobs
    "#1E9E5A",  # 5 green knobs
    "#1F4FB0",  # 6 blue knobs
    "#7B5BB5",  # 7 purple knobs
    "#B8BCBF",  # 8 light gray: outlet and icon panels
]
CHARCOAL, WHITE, RED, YELLOW, GREEN, BLUE, PURPLE, LIGHT_GRAY = range(1, 9)

# --- Overall ----------------------------------------------------------------
HEIGHT = 203.2
HOOD_HALF_W = 52.35          # hood width 104.7
BASE_HALF_W = 50.5           # base cabinet a little narrower
BACK_Y = 35.9

# --- Base cabinet -----------------------------------------------------------
TOE_TOP, TOE_FRONT_Y = 6.0, -19.6
BASE_TOP, BASE_FRONT_Y = 76.0, -27.2
DOOR_TOP = 60.4              # top edge of the doors; apron above
GROOVE_W, GROOVE_D = 0.8, 0.6
HANDLE_X, HANDLE_Z, HANDLE_LEN, HANDLE_W, HANDLE_PROUD = 7.5, 45.0, 9.6, 2.2, 1.6

# --- Work surface and hood --------------------------------------------------
COUNTER_TOP, COUNTER_FRONT_Y = 80.0, -33.1
HOOD_FRONT_Y = -33.0
OPEN_HALF_W, OPEN_TOP, OPEN_BACK_Y = 41.75, 164.0, 30.6
LINER_T = 1.2
LIP_H, LIP_D = 1.5, 2.5      # raised front lip of the work surface
SASH_Z0, SASH_Z1, SASH_D = 91.7, 94.0, 2.5
BAFFLE_X = (-35.3, -15.6, 16.1, 36.0)
BAFFLE_Z0, BAFFLE_Z1, BAFFLE_W, BAFFLE_PROUD = 88.6, 145.0, 1.0, 0.6

# --- Header -----------------------------------------------------------------
HEADER_BOTTOM, HEADER_FRONT_Y, HEADER_CHAMFER = 165.0, -35.6, 2.0

# --- Fixtures on the posts --------------------------------------------------
KNOB_Z = (129.1, 121.3, 113.5, 105.7, 98.1)                   # top to bottom
LEFT_KNOBS = (None, YELLOW, RED, GREEN, BLUE)                   # None = small dark screw
RIGHT_KNOBS = (PURPLE, YELLOW, RED, GREEN, BLUE)
INNER_VALVES = (PURPLE, YELLOW, RED, GREEN, BLUE)               # T-valves on the inner side walls
KNOB_X, KNOB_R, KNOB_STEM = 45.2, 1.85, 1.4
VALVE_Y, VALVE_STEM_R, VALVE_STEM_L, VALVE_BAR = -28.0, 0.75, 2.0, (1.0, 1.0, 3.2)
PANEL_PROUD = 0.6
ICON_PANEL = (-48.9, -43.2, 135.5, 143.4)                       # x0, x1, z0, z1 (left post)
OUTLET_PANEL_X, OUTLET_PANEL_W, OUTLET_PANEL_Z = 46.6, 8.2, (81.0, 90.0)

# --- Label ------------------------------------------------------------------
LABEL = (23.3, 48.5, 168.1, 174.6)                              # x0, x1, z0, z1 on the header
LABEL_PLATE_T, LETTER_T, LETTER_H, LABEL_MARGIN = 0.8, 0.6, 4.4, 0.9
LABEL_TEXT = "VENTURI"


# Rotate -90 deg about X: the front (-Y) faces +Z, the back (+Y) goes down onto the bed.
ON_BACK = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])


def box(x0, x1, y0, y1, z0, z1) -> trimesh.Trimesh:
    b = trimesh.creation.box(extents=[x1 - x0, y1 - y0, z1 - z0])
    b.apply_translation([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
    return b


def union(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    return trimesh.boolean.union(meshes, engine="manifold") if len(meshes) > 1 else meshes[0]


def front_cylinder(x: float, z: float, r: float, y_face: float, length: float, sections: int = 32):
    """Cylinder sticking out of a front face (toward -Y)."""
    c = trimesh.creation.cylinder(radius=r, height=length, sections=sections)
    c.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    c.apply_translation([x, y_face - length / 2, z])
    return c


def knob(x: float, z: float) -> trimesh.Trimesh:
    """Stem plus domed cap, like the push-on knobs on the model."""
    stem = front_cylinder(x, z, KNOB_R * 0.8, HOOD_FRONT_Y, KNOB_STEM)
    cap = trimesh.creation.icosphere(subdivisions=3, radius=KNOB_R)
    # Cap center far enough out that the dome never reaches back into the post (no color overlap).
    cap.apply_translation([x, HOOD_FRONT_Y - KNOB_STEM - KNOB_R * 0.5, z])
    return union([stem, cap])


def valve(side: int, z: float) -> trimesh.Trimesh:
    """T-shaped valve on the inner side wall, pointing into the opening. side = -1 left, +1 right."""
    wall_x = side * (OPEN_HALF_W - LINER_T)
    stem = trimesh.creation.cylinder(radius=VALVE_STEM_R, height=VALVE_STEM_L, sections=24)
    stem.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    stem.apply_translation([wall_x - side * VALVE_STEM_L / 2, VALVE_Y, z])
    bx, by, bz = VALVE_BAR
    tip = wall_x - side * VALVE_STEM_L
    bar = box(min(tip, tip - side * bx), max(tip, tip - side * bx), VALVE_Y - by / 2, VALVE_Y + by / 2,
              z - bz / 2, z + bz / 2)
    return union([stem, bar])


def text_solid(text: str, max_w: float, max_h: float, depth: float, center_x: float, center_z: float,
               y_face: float):
    """Raised lettering on a front face, fitted inside max_w x max_h, extruded `depth` toward -Y."""
    path = TextPath((0, 0), text, size=10, prop=FontProperties(family="DejaVu Sans", weight="bold"))
    rings = [sg.Polygon(p) for p in path.to_polygons() if len(p) >= 3]
    rings = [r.buffer(0) for r in rings if r.area > 1e-6]
    rings.sort(key=lambda r: -r.area)
    glyphs: list[sg.Polygon] = []
    for ring in rings:  # a ring inside an existing glyph is a hole (e.g. in R)
        for i, g in enumerate(glyphs):
            if g.contains(ring):
                glyphs[i] = g.difference(ring)
                break
        else:
            glyphs.append(ring)
    shape = sg.MultiPolygon([p for g in glyphs for p in getattr(g, "geoms", [g])])
    minx, miny, maxx, maxy = shape.bounds
    scale = min(max_w / (maxx - minx), max_h / (maxy - miny))
    # Scale the 2D outlines first so the extrusion depth stays exactly `depth`.
    shape = sg.MultiPolygon([sg.Polygon(np.asarray(p.exterior.coords) * scale,
                                        [np.asarray(i.coords) * scale for i in p.interiors]) for p in shape.geoms])
    solids = []
    for poly in shape.geoms:
        m = trimesh.creation.extrude_polygon(poly, depth)
        # 2D (x, y) + extrusion z  ->  world (x, -extrusion, y)
        m.apply_transform(np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=float))
        solids.append(m)
    letters = trimesh.util.concatenate(solids)
    lo, hi = letters.bounds
    letters.apply_translation([center_x - (lo[0] + hi[0]) / 2, y_face - hi[1], center_z - (lo[2] + hi[2]) / 2])
    return union(solids_split(letters))


def solids_split(mesh: trimesh.Trimesh) -> list[trimesh.Trimesh]:
    return list(mesh.split(only_watertight=False))


def build() -> list[bambu3mf.Part]:
    # --- Charcoal body ---
    toe = box(-BASE_HALF_W, BASE_HALF_W, TOE_FRONT_Y, BACK_Y, 0, TOE_TOP)
    base = box(-BASE_HALF_W, BASE_HALF_W, BASE_FRONT_Y, BACK_Y, TOE_TOP, BASE_TOP)
    counter = box(-HOOD_HALF_W, HOOD_HALF_W, COUNTER_FRONT_Y, BACK_Y, BASE_TOP, COUNTER_TOP)
    hood = box(-HOOD_HALF_W, HOOD_HALF_W, HOOD_FRONT_Y, BACK_Y, COUNTER_TOP, HEADER_BOTTOM)
    c = HEADER_CHAMFER
    header = trimesh.convex.convex_hull(np.array([
        [x, y, z] for x in (-HOOD_HALF_W, HOOD_HALF_W) for y, z in (
            (HEADER_FRONT_Y, HEADER_BOTTOM), (HEADER_FRONT_Y, HEIGHT - c), (HEADER_FRONT_Y + c, HEIGHT),
            (BACK_Y, HEIGHT), (BACK_Y, HEADER_BOTTOM))
    ]))
    body = union([toe, base, counter, hood, header])

    cavity = box(-OPEN_HALF_W, OPEN_HALF_W, HOOD_FRONT_Y - 5, OPEN_BACK_Y, COUNTER_TOP, OPEN_TOP)
    grooves = [
        box(-BASE_HALF_W - 1, BASE_HALF_W + 1, BASE_FRONT_Y - 1, BASE_FRONT_Y + GROOVE_D,
            DOOR_TOP - GROOVE_W / 2, DOOR_TOP + GROOVE_W / 2),
        box(-GROOVE_W / 2, GROOVE_W / 2, BASE_FRONT_Y - 1, BASE_FRONT_Y + GROOVE_D, TOE_TOP, DOOR_TOP),
    ]
    body = trimesh.boolean.difference([body, cavity, *grooves], engine="manifold")

    handles = []
    for sx in (-1, 1):
        h = trimesh.creation.capsule(height=HANDLE_LEN - HANDLE_W, radius=HANDLE_W / 2, count=[16, 16])
        h.apply_scale([1, HANDLE_PROUD / (HANDLE_W / 2), 1])  # flatten toward the door
        h.apply_translation([sx * HANDLE_X, BASE_FRONT_Y, HANDLE_Z])
        handles.append(h)
    lip = box(-OPEN_HALF_W, OPEN_HALF_W, HOOD_FRONT_Y, HOOD_FRONT_Y + LIP_D, COUNTER_TOP, COUNTER_TOP + LIP_H)
    inner = OPEN_HALF_W - LINER_T
    sash = box(-inner, inner, HOOD_FRONT_Y, HOOD_FRONT_Y + SASH_D, SASH_Z0, SASH_Z1)
    back_face = OPEN_BACK_Y - LINER_T
    baffles = [box(x - BAFFLE_W / 2, x + BAFFLE_W / 2, back_face - BAFFLE_PROUD, back_face, BAFFLE_Z0, BAFFLE_Z1)
               for x in BAFFLE_X]
    screw = front_cylinder(-KNOB_X, KNOB_Z[0], 0.9, HOOD_FRONT_Y, 0.5)
    outlets = []
    for sx in (-1, 1):
        for dx in (-1.6, 1.6):
            outlets.append(box(sx * OUTLET_PANEL_X + dx - 0.7, sx * OUTLET_PANEL_X + dx + 0.7,
                               HOOD_FRONT_Y - PANEL_PROUD - 0.3, HOOD_FRONT_Y - PANEL_PROUD,
                               OUTLET_PANEL_Z[0] + 2.0, OUTLET_PANEL_Z[1] - 2.0))
    # Handles sink into the door slightly so they fuse with it.
    body = union([body, *[h.apply_translation([0, 0.3, 0]) for h in handles], lip, sash, *baffles, screw, *outlets])

    # --- White interior liner and label plate ---
    liner = trimesh.boolean.difference([
        box(-OPEN_HALF_W, OPEN_HALF_W, HOOD_FRONT_Y, OPEN_BACK_Y, COUNTER_TOP + LIP_H, OPEN_TOP),
        box(-inner, inner, HOOD_FRONT_Y - 1, back_face, COUNTER_TOP, OPEN_TOP - LINER_T),
    ], engine="manifold")
    # Keep the liner off the lip, sash and baffles (those are charcoal parts touching it).
    liner = trimesh.boolean.difference([liner, lip, sash, *baffles], engine="manifold")
    lx0, lx1, lz0, lz1 = LABEL
    plate = box(lx0, lx1, HEADER_FRONT_Y - LABEL_PLATE_T, HEADER_FRONT_Y, lz0, lz1)
    white = union([liner, plate])

    # --- Colored fixtures ---
    by_color: dict[int, list[trimesh.Trimesh]] = {k: [] for k in (RED, YELLOW, GREEN, BLUE, PURPLE)}
    for z, color in zip(KNOB_Z, LEFT_KNOBS):
        if color:
            by_color[color].append(knob(-KNOB_X, z))
    for z, color in zip(KNOB_Z, RIGHT_KNOBS):
        by_color[color].append(knob(KNOB_X, z))
    for z, color in zip(KNOB_Z, INNER_VALVES):
        by_color[color] += [valve(-1, z), valve(1, z)]
    letters = text_solid(LABEL_TEXT, lx1 - lx0 - 2 * LABEL_MARGIN, LETTER_H, LETTER_T, (lx0 + lx1) / 2,
                         (lz0 + lz1) / 2, HEADER_FRONT_Y - LABEL_PLATE_T)
    by_color[RED].append(letters)

    x0, x1, z0, z1 = ICON_PANEL
    panels = [box(x0, x1, HOOD_FRONT_Y - PANEL_PROUD, HOOD_FRONT_Y, z0, z1)]
    for sx in (-1, 1):
        cx = sx * OUTLET_PANEL_X
        panels.append(box(cx - OUTLET_PANEL_W / 2, cx + OUTLET_PANEL_W / 2, HOOD_FRONT_Y - PANEL_PROUD,
                          HOOD_FRONT_Y, *OUTLET_PANEL_Z))

    names = {RED: "red knobs + letters", YELLOW: "yellow knobs", GREEN: "green knobs", BLUE: "blue knobs",
             PURPLE: "purple knobs"}
    parts = [bambu3mf.Part("body", body, CHARCOAL), bambu3mf.Part("white interior + label plate", white, WHITE)]
    parts += [bambu3mf.Part(names[c], union(ms), c) for c, ms in by_color.items()]
    parts.append(bambu3mf.Part("gray panels", union(panels), LIGHT_GRAY))
    return parts


def check(parts: list[bambu3mf.Part]) -> dict:
    """Each part closed; parts touch but don't overlap; overall size."""
    report = {"parts": {}, "overlaps_mm3": {}}
    for p in parts:
        report["parts"][p.name] = {"filament": p.filament, "watertight": bool(p.mesh.is_watertight),
                                   "volume_cm3": round(float(p.mesh.volume) / 1000, 3),
                                   "bodies": len(p.mesh.split(only_watertight=False))}
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            if not (np.all(a.mesh.bounds[0] <= b.mesh.bounds[1]) and np.all(b.mesh.bounds[0] <= a.mesh.bounds[1])):
                continue
            inter = trimesh.boolean.intersection([a.mesh, b.mesh], engine="manifold")
            with np.errstate(divide="ignore", invalid="ignore"):
                vol = float(inter.volume) if len(inter.faces) else 0.0
            if vol > 1e-3:
                report["overlaps_mm3"][f"{a.name} / {b.name}"] = round(vol, 4)
    allm = trimesh.util.concatenate([p.mesh for p in parts])
    report["extents_mm"] = [round(float(v), 2) for v in allm.extents]
    report["min_z"] = round(float(allm.bounds[0][2]), 4)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("output/cad-isolator"))
    ap.add_argument("--upright", action="store_true",
                    help="Write print files standing up instead of lying on the back (needs far more support)")
    args = ap.parse_args(argv)
    parts = build()
    report = check(parts)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    tri = np.concatenate([p.mesh.triangles for p in parts])
    colors = np.concatenate([np.tile(printprep.hex_to_rgb(PALETTE)[p.filament - 1], (len(p.mesh.faces), 1))
                             for p in parts])
    printprep.render_colored_faces(tri, colors, out / "isolator-colors.png", "CAD isolator, 8 filaments")

    if not args.upright:
        # Lying on its back: no support except under the sash bar, flat back on the bed, front on top.
        for p in parts:
            p.mesh.apply_transform(ON_BACK)
    report["print_orientation"] = "upright" if args.upright else "on its back, front facing up"
    bambu3mf.write(parts, PALETTE, out / "isolator-8color.3mf", name="VENTURI isolator")
    for p in parts:
        p.mesh.export(out / f"part-{p.filament}-{p.name.split()[0]}.stl")
    combined = union([p.mesh for p in parts])
    combined.apply_translation([0, 0, -combined.bounds[0][2]])
    combined.export(out / "isolator-single-color.stl")
    printprep.render_preview(combined, out / "isolator-preview.png")
    report["single_color"] = printprep.report(combined).to_dict()
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
