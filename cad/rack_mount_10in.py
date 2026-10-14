"""2U 10-inch rack shelf for a mini PC (default: GMKtec NucBox M3 Pro, 114 x 106 x 42.5 mm) with a
pass-through bay next to it for a JetKVM: its 24 mm tall body slides in from the front through a
43 x 24 mm (+ clearance) opening and the taller screen head (31 mm) stays in front of the faceplate.

Coordinates (mm): X across the rack (centered), Y depth (faceplate front at y=0, tray toward +Y),
Z up (rack unit boundary at z=0). Print it face-down: the faceplate is the first layers and the tray
grows straight up, so nothing needs support.

Sources for the numbers:
- PC size: GMKtec's product page (114 x 106 x 42.5 mm), confirmed by the user's unit.
- JetKVM: the maker's dimension drawing (shared by the user): 43 mm wide, 60 mm long, body 24 mm
  tall with a 31 mm tall screen head at the front; USB-C / HDMI / Ethernet / RJ11 on the back.
  The head's depth isn't dimensioned on the drawing; ~30 mm is scaled from it (only used for the preview).
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

# --- JetKVM bay (beside the PC; body through the faceplate, screen head out front, cables out back) --
KVM_W, KVM_BODY_H, KVM_HEAD_H, KVM_D = 43.0, 24.0, 31.0, 60.0
KVM_HEAD_D = 30.0                # head depth, scaled from the drawing (preview only)
KVM_CLEAR = 0.5                  # per side; the body sits on the floor, so the height gets 2x on top
BAY_GAP = 12.0                   # PC pocket to JetKVM pocket: a wall on each side, open space between
TIE_W, TIE_L = 2.5, 5.0          # zip-tie slots in the floor (fit ties up to ~4.5 mm wide, 2 mm thick)
TIE_Y = 45.0                     # slot center, from the faceplate front: behind the JetKVM's ~30 mm body
TIE_SPAN = 26.0                  # center-to-center of the two slots (the tie goes down one, up the other)

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


def layout() -> dict:
    """X positions: PC pocket on the left, JetKVM pocket on the right, the pair centered in the rack."""
    pc_w = PC_W + 2 * CLEAR
    kvm_w = KVM_W + 2 * KVM_CLEAR
    # Outer extent: gusset + wall | PC pocket | shared wall | KVM pocket | wall + gusset
    total = 2 * (WALL_T + WALL_T) + pc_w + BAY_GAP + kvm_w
    x0 = -total / 2 + 2 * WALL_T
    pc = (x0, x0 + pc_w)
    kvm = (pc[1] + BAY_GAP, pc[1] + BAY_GAP + kvm_w)
    return {"pc": pc, "kvm": kvm, "outer": (-total / 2, total / 2)}


def floor_top() -> float:
    return (UNITS * U - (PC_H + CLEAR)) / 2          # PC centered in the 2U space


def build() -> tuple[trimesh.Trimesh, dict]:
    lay = layout()
    pocket_d, pocket_h = PC_D + TRAY_EXTRA_D, PC_H + CLEAR
    kvm_h = KVM_BODY_H + 2 * KVM_CLEAR
    panel_z0 = 0.79 / 2
    ft = floor_top()
    floor_bot = ft - FLOOR_T
    (pc0, pc1), (k0, k1) = lay["pc"], lay["kvm"]
    out0, out1 = pc0 - WALL_T, k1 + WALL_T
    tray_y1 = PANEL_T + pocket_d

    panel = rounded_panel(-PANEL_W / 2, PANEL_W / 2, panel_z0, panel_z0 + PANEL_H, PANEL_CORNER_R, PANEL_T)
    floor = box(out0, out1, PANEL_T - 0.01, tray_y1, floor_bot, ft)
    walls = [box(pc0, out0, PANEL_T - 0.01, tray_y1, floor_bot, ft + WALL_H),       # left of the PC
             box(pc1, pc1 + WALL_T, PANEL_T - 0.01, tray_y1, floor_bot, ft + WALL_H),  # right of the PC
             box(k0 - WALL_T, k0, PANEL_T - 0.01, tray_y1, floor_bot, ft + WALL_H),    # left of the JetKVM
             box(k1, out1, PANEL_T - 0.01, tray_y1, floor_bot, ft + WALL_H)]        # right of the JetKVM
    braces = [gusset(out0, out0 - WALL_T, ft, GUSSET), gusset(out1, out1 + WALL_T, ft, GUSSET)]
    # Corner stops: small squares left in each window's corners, within the faceplate's thickness.
    # Devices slide in from the back and stop against them; ports, button and screen stay clear.
    tabs = []
    # The JetKVM needs none: its taller head rests against the faceplate above the opening.
    for (a, b), h, t in (((pc0, pc1), pocket_h, STOP_TAB),):
        for x_in, x_edge in ((a, a + t), (b - t, b)):
            for z in (ft, ft + h - t):
                tabs.append(box(x_in - (0.01 if x_in == a else 0), x_edge + (0.01 if x_edge == b else 0),
                                0, PANEL_T, z, z + t))
    body = union([panel, floor, *walls, *braces])

    windows = [box(pc0, pc1, -1, PANEL_T + 1, ft, ft + pocket_h), box(k0, k1, -1, PANEL_T + 1, ft, ft + kvm_h)]
    centers = np.mean(HOLE_SPAN) / 2
    half_len = (HOLE_SPAN[1] - HOLE_SPAN[0]) / 4 + SLOT_EXTRA / 2
    slots = [slot(s * centers, z, half_len, SLOT_W, PANEL_T) for s in (-1, 1) for z in HOLE_Z]
    vents = []
    n = int((pc1 - pc0 - 2 * VENT_MARGIN + VENT_GAP) // (VENT_W + VENT_GAP))
    span = n * VENT_W + (n - 1) * VENT_GAP
    mid = (pc0 + pc1) / 2
    for i in range(n):
        x0 = mid - span / 2 + i * (VENT_W + VENT_GAP)
        vents.append(box(x0, x0 + VENT_W, PANEL_T + VENT_MARGIN, tray_y1 - VENT_MARGIN, floor_bot - 1, ft + 1))
    # Zip-tie slots behind the JetKVM: strap its cables to the floor so a tug from the back can't pull
    # it out. Long side along the depth, so printed face-down each slot only bridges TIE_W.
    kmid = (k0 + k1) / 2
    ties = [box(kmid + s * TIE_SPAN / 2 - TIE_W / 2, kmid + s * TIE_SPAN / 2 + TIE_W / 2,
                TIE_Y - TIE_L / 2, TIE_Y + TIE_L / 2, floor_bot - 1, ft + 1) for s in (-1, 1)]
    body = diff(body, [*windows, *slots, *vents, *ties])
    body = union([body, *tabs])

    info = {
        "pc_pocket_mm": [round(pc1 - pc0, 2), round(pocket_d, 2), round(pocket_h, 2)],
        "pc_mm": [PC_W, PC_D, PC_H],
        "pc_center_x_mm": round(mid, 2),
        "kvm_window_mm": [round(k1 - k0, 2), round(kvm_h, 2)],
        "kvm_mm": {"width": KVM_W, "body_h": KVM_BODY_H, "head_h": KVM_HEAD_H, "length": KVM_D},
        "kvm_head_overlap_above_opening_mm": round(KVM_HEAD_H - kvm_h, 2),
        "kvm_center_x_mm": round((k0 + k1) / 2, 2),
        "panel_mm": [PANEL_W, round(PANEL_H, 2), PANEL_T],
        "tray_outer_width_mm": round(out1 - out0, 2),
        "tray_with_braces_mm": round(lay["outer"][1] - lay["outer"][0], 2),
        "tray_fits_rail_opening": bool(lay["outer"][1] - lay["outer"][0] < OPENING_W),
        "slot_center_range_mm": [round(2 * (centers - half_len), 2), round(2 * (centers + half_len), 2)],
        "slot_edge_to_panel_edge_mm": round(PANEL_W / 2 - centers - half_len - SLOT_W / 2, 2),
        "pc_bottom_z_mm": round(ft, 2),
        "vent_slots": n,
        "pc_to_kvm_gap_mm": BAY_GAP,
        "zip_tie_slots_mm": {"size": [TIE_W, TIE_L], "center_y": TIE_Y, "span": TIE_SPAN,
                             "behind_kvm_body_end_mm": round(TIE_Y - TIE_L / 2 - (KVM_D - KVM_HEAD_D), 2)},
    }
    return body, info


def pc_dummy() -> trimesh.Trimesh:
    pc0 = layout()["pc"][0] + CLEAR
    return box(pc0, pc0 + PC_W, PANEL_T, PANEL_T + PC_D, floor_top(), floor_top() + PC_H)


def kvm_dummy() -> trimesh.Trimesh:
    """Body through the opening, head in front of the faceplate (front of the head at y = -KVM_HEAD_D)."""
    k0, z0 = layout()["kvm"][0] + KVM_CLEAR, floor_top()
    body = box(k0, k0 + KVM_W, -KVM_HEAD_D, KVM_D - KVM_HEAD_D, z0, z0 + KVM_BODY_H)
    head = box(k0, k0 + KVM_W, -KVM_HEAD_D, -0.01, z0 + KVM_BODY_H - 0.01, z0 + KVM_HEAD_H)
    return union([body, head])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="2U 10-inch rack shelf for a mini PC + JetKVM")
    ap.add_argument("--out", type=Path, default=Path("output/cad-rack-m3pro"))
    args = ap.parse_args(argv)
    body, info = build()
    pc, kvm = pc_dummy(), kvm_dummy()
    for key, dev in (("pc_overlap_mm3", pc), ("kvm_overlap_mm3", kvm)):
        inter = trimesh.boolean.intersection([body, dev], engine="manifold")
        info[key] = round(float(inter.volume), 3) if len(inter.faces) else 0.0
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
    rgb = printprep.hex_to_rgb(["#3A3F45", "#B8BEC6", "#E0A030"])
    for name, angle in (("front", 0), ("back", 180), ("angled", -35), ("angled-back", 145)):
        tri = np.concatenate([body.triangles, pc.triangles, kvm.triangles])
        cols = np.vstack([np.tile(rgb[0], (len(body.faces), 1)), np.tile(rgb[1], (len(pc.faces), 1)),
                          np.tile(rgb[2], (len(kvm.faces), 1))])
        printprep.render_colored_faces(tri, cols, out / f"view-{name}.png", "", views=((angle, name),), px_per_mm=4)
    # Top-down view (floor, vents, zip-tie slots): tip the model so +Z faces the renderer's camera (-Y).
    tip = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
    tri = np.concatenate([m.copy().apply_transform(tip).triangles for m in (body, pc, kvm)])
    cols = np.vstack([np.tile(rgb[i], (len(m.faces), 1)) for i, m in enumerate((body, pc, kvm))])
    printprep.render_colored_faces(tri, cols, out / "view-top.png", "", views=((0, "top"),), px_per_mm=4)
    tri = tri[: len(body.faces)]
    printprep.render_colored_faces(tri, cols[: len(body.faces)], out / "view-top-empty.png", "",
                                   views=((0, "top, devices removed"),), px_per_mm=4)
    (out / "report.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
