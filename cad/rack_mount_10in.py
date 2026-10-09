"""2U 10-inch rack shelf for a mini PC (default: GMKtec NucBox M3 Pro, 114 x 106 x 42.5 mm).

Coordinates (mm): X across the rack (centered), Y depth (faceplate front at y=0, tray toward +Y),
Z up (rack unit boundary at z=0). Print it face-down: the faceplate is the first layers and the tray
grows straight up, so nothing needs support.

Sources for the numbers:
- PC size: GMKtec's product page (114 x 106 x 42.5 mm), confirmed by the user's unit.
- Rack: 1U = 44.45 mm; a panel is 1/32" (0.79 mm) shorter than its units; holes per U at 6.35,
  22.225 and 38.1 mm (EIA-310 pattern); 10" panel width 254 mm; clear opening between rails
  222.25 mm. Hole spacing: sources quote ~235 / 236.5 mm for 10" racks, but the user's rack measures
  ~240 mm center-to-center (ruler), so the slots are centered on 240 mm and span 238-242 mm.

Run: python -m cad.rack_mount_10in [--out DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh

from meshy3d import printprep

# --- PC ---------------------------------------------------------------------
PC_W, PC_D, PC_H = 114.0, 106.0, 42.5
CLEAR = 0.8                      # per side, around the PC

# --- Rack -------------------------------------------------------------------
U = 44.45
UNITS = 2
PANEL_W = 254.0
PANEL_H = UNITS * U - 0.79
PANEL_T = 4.0
PANEL_CORNER_R = 5.0             # rounded outer corners of the faceplate (seen from the front)
OPENING_W = 222.25               # clear width between the rails
HOLE_Z = (6.35, 38.1, 6.35 + U, 38.1 + U)  # top and bottom hole of each U
HOLE_SPAN = (238.0, 242.0)       # center-to-center range the slots cover (user measured ~240 mm)
SLOT_W = 6.5                     # M6 clearance
SLOT_EXTRA = 0.0                 # extra slot length beyond HOLE_SPAN, each side

# --- Tray -------------------------------------------------------------------
FLOOR_T = 3.0
WALL_T = 3.0
WALL_H = 22.0                    # side wall height above the floor
TRAY_EXTRA_D = 2.0               # tray a bit deeper than the PC
STOP_TAB = 4.0                   # corner tabs on the back of the faceplate that stop the PC
GUSSET = 30.0                    # triangular braces from faceplate to side walls
VENT_W, VENT_GAP, VENT_MARGIN = 5.0, 4.0, 10.0
WINDOW_R = 0.0                   # sharp window corners (simple to print face-down)


def box(x0, x1, y0, y1, z0, z1) -> trimesh.Trimesh:
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    z0, z1 = sorted((z0, z1))
    b = trimesh.creation.box(extents=[x1 - x0, y1 - y0, z1 - z0])
    b.apply_translation([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
    return b


def union(ms):
    return trimesh.boolean.union(ms, engine="manifold")


def diff(a, ms):
    return trimesh.boolean.difference([a, *ms], engine="manifold")


def rounded_panel(x0: float, x1: float, z0: float, z1: float, r: float, t: float) -> trimesh.Trimesh:
    """Faceplate: rectangle in the X-Z plane with rounded corners, extruded from y=0 back to y=t."""
    import shapely.geometry as sg

    outline = sg.box(x0 + r, z0 + r, x1 - r, z1 - r).buffer(r, quad_segs=16) if r > 0 else sg.box(x0, z0, x1, z1)
    m = trimesh.creation.extrude_polygon(outline, t)
    # 2D (x, z) + extrusion -> world (x, y = t - extrusion, z); proper rotation (no mirroring).
    m.apply_transform(np.array([[1, 0, 0, 0], [0, 0, -1, t], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=float))
    return m


def slot(cx: float, cz: float, half_len: float, width: float, depth: float) -> trimesh.Trimesh:
    """Horizontal slot (along X) through the faceplate (along Y)."""
    r = width / 2
    parts = [box(cx - half_len, cx + half_len, -1, depth + 1, cz - r, cz + r)]
    for x in (cx - half_len, cx + half_len):
        c = trimesh.creation.cylinder(radius=r, height=depth + 2, sections=48)
        c.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
        c.apply_translation([x, depth / 2, cz])
        parts.append(c)
    return union(parts)


def gusset(x0: float, x1: float, z0: float, size: float) -> trimesh.Trimesh:
    """Right-triangle brace in the Y-Z plane: along the faceplate back up `size`, along the tray `size`."""
    pts = []
    for x in (x0, x1):
        pts += [[x, PANEL_T, z0], [x, PANEL_T + size, z0], [x, PANEL_T, z0 + size]]
    return trimesh.convex.convex_hull(np.array(pts))


def build() -> tuple[trimesh.Trimesh, dict]:
    pocket_w, pocket_d, pocket_h = PC_W + 2 * CLEAR, PC_D + TRAY_EXTRA_D, PC_H + CLEAR
    panel_z0 = 0.79 / 2
    floor_top = (UNITS * U - pocket_h) / 2          # PC centered in the 2U space
    floor_bot = floor_top - FLOOR_T
    half_in = pocket_w / 2
    half_out = half_in + WALL_T
    tray_y1 = PANEL_T + pocket_d

    panel = rounded_panel(-PANEL_W / 2, PANEL_W / 2, panel_z0, panel_z0 + PANEL_H, PANEL_CORNER_R, PANEL_T)
    floor = box(-half_out, half_out, PANEL_T - 0.01, tray_y1, floor_bot, floor_top)
    walls = [box(s * half_in, s * half_out, PANEL_T - 0.01, tray_y1, floor_bot, floor_top + WALL_H)
             for s in (-1, 1)]
    braces = [gusset(s * half_out, s * (half_out + WALL_T), floor_top, GUSSET) for s in (-1, 1)]
    # Corner stops: small squares left in the window's corners, within the faceplate's thickness.
    # The PC slides in from the back and stops against them; ports and button stay clear.
    tabs = []
    for sx in (-1, 1):
        for z in (floor_top, floor_top + pocket_h - STOP_TAB):
            x_in = sx * (half_in - STOP_TAB)
            tabs.append(box(x_in, sx * half_in + sx * 0.01, 0, PANEL_T, z, z + STOP_TAB))
    body = union([panel, floor, *walls, *braces])

    window = box(-half_in, half_in, -1, PANEL_T + 1, floor_top, floor_top + pocket_h)
    centers = np.mean(HOLE_SPAN) / 2
    half_len = (HOLE_SPAN[1] - HOLE_SPAN[0]) / 4 + SLOT_EXTRA / 2
    slots = [slot(s * centers, z, half_len, SLOT_W, PANEL_T) for s in (-1, 1) for z in HOLE_Z]
    vents = []
    n = int((pocket_w - 2 * VENT_MARGIN + VENT_GAP) // (VENT_W + VENT_GAP))
    span = n * VENT_W + (n - 1) * VENT_GAP
    for i in range(n):
        x0 = -span / 2 + i * (VENT_W + VENT_GAP)
        vents.append(box(x0, x0 + VENT_W, PANEL_T + VENT_MARGIN, tray_y1 - VENT_MARGIN, floor_bot - 1, floor_top + 1))
    body = diff(body, [window, *slots, *vents])
    body = union([body, *tabs])

    info = {
        "pocket_mm": [round(pocket_w, 2), round(pocket_d, 2), round(pocket_h, 2)],
        "pc_mm": [PC_W, PC_D, PC_H],
        "window_mm": [round(pocket_w, 2), round(pocket_h, 2)],
        "panel_mm": [PANEL_W, round(PANEL_H, 2), PANEL_T],
        "tray_outer_width_mm": round(2 * half_out, 2),
        "tray_fits_rail_opening": bool(2 * (half_out + WALL_T) < OPENING_W),
        "slot_center_range_mm": [round(2 * (centers - half_len), 2), round(2 * (centers + half_len), 2)],
        "slot_edge_to_panel_edge_mm": round(PANEL_W / 2 - centers - half_len - SLOT_W / 2, 2),
        "pc_bottom_z_mm": round(floor_top, 2),
        "pc_top_z_mm": round(floor_top + PC_H, 2),
        "vent_slots": n,
    }
    return body, info


def pc_dummy() -> trimesh.Trimesh:
    pocket_h = PC_H + CLEAR
    floor_top = (UNITS * U - pocket_h) / 2
    return box(-PC_W / 2, PC_W / 2, PANEL_T, PANEL_T + PC_D, floor_top, floor_top + PC_H)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="2U 10-inch rack shelf for a mini PC")
    ap.add_argument("--out", type=Path, default=Path("output/cad-rack-m3pro"))
    args = ap.parse_args(argv)
    body, info = build()
    pc = pc_dummy()
    inter = trimesh.boolean.intersection([body, pc], engine="manifold")
    info["pc_overlap_mm3"] = round(float(inter.volume), 3) if len(inter.faces) else 0.0
    info["watertight"] = bool(body.is_watertight)
    info["bodies"] = len(body.split(only_watertight=False))
    info["extents_mm"] = [round(float(v), 2) for v in body.extents]
    info["volume_cm3"] = round(float(body.volume) / 1000, 1)

    # Print orientation: faceplate down. +90 deg about X sends the front (-Y) to -Z, onto the bed.
    to_bed = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
    printable = body.copy().apply_transform(to_bed)
    printable.apply_translation(-printable.bounds[0] * [0, 0, 1])
    info["print_footprint_mm"] = [round(float(v), 2) for v in printable.extents[:2]]
    info["print_height_mm"] = round(float(printable.extents[2]), 2)
    n, c, a = printable.face_normals, printable.triangles_center, printable.area_faces
    over = (n[:, 2] < -np.cos(np.radians(45))) & (c[:, 2] > 0.05)
    info["overhang_mm2_needing_support"] = round(float(a[over].sum()), 1)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    printable.export(out / "rack-mount-m3pro.stl")
    printable.export(out / "rack-mount-m3pro.3mf")
    rgb = printprep.hex_to_rgb(["#3A3F45", "#B8BEC6"])
    for name, angle in (("front", 0), ("back", 180), ("angled", -35), ("angled-back", 145)):
        tri = np.concatenate([body.triangles, pc.triangles])
        cols = np.vstack([np.tile(rgb[0], (len(body.faces), 1)), np.tile(rgb[1], (len(pc.faces), 1))])
        printprep.render_colored_faces(tri, cols, out / f"view-{name}.png", "", views=((angle, name),), px_per_mm=4)
    (out / "report.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
