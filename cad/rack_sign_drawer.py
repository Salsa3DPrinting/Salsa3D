"""1U 10-inch rack sign with a drawer: the drawer front reads "Salsa Homelab".

Two prints:
- Frame: 1U faceplate (same slotted rack holes as cad/rack_mount_10in.py) with a window and a sleeve
  behind it. Prints face-down: the faceplate is the first layers and the sleeve grows straight up
  (open back), so nothing needs support.
- Drawer: an open-top box that slides into the sleeve. Its front plate overlaps the window and is the
  stop. The text is a flush two-color inlay in that front, with a finger pull under it. Prints upright
  (floor on the bed); the only bridge is the finger pull's 4 mm deep roof.

Coordinates (mm): X across the rack (centered), Y depth (faceplate front at y=0, toward +Y), Z up
(rack unit boundary at z=0).

Run: python -m cad.rack_sign_drawer [--out DIR] [--text1 Salsa --text2 Homelab]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import shapely.geometry as sg
import trimesh
from shapely.affinity import scale, translate
from shapely.ops import unary_union

from cad import rack_mount_10in as rack
from cad.name_tag import drop_slivers, extrude
from cad.rack_mount_10in import box, diff, rounded_panel, slot, union
from meshy3d import bambu3mf, printprep

U, PANEL_W, PANEL_T, PANEL_CORNER_R = rack.U, rack.PANEL_W, rack.PANEL_T, rack.PANEL_CORNER_R
HOLE_SPAN, SLOT_W, SLOT_EXTRA, OPENING_W = rack.HOLE_SPAN, rack.SLOT_W, rack.SLOT_EXTRA, rack.OPENING_W
PANEL_H = U - 0.79
HOLE_Z = (6.35, 38.1)                # top and bottom hole of the unit (EIA-310 pattern)

SLEEVE_W, SLEEVE_H = 218.0, 41.0     # outside; must pass between the rails (OPENING_W)
SLEEVE_WALL = 2.0
SLEEVE_D = 200.0                     # depth behind the faceplate (check against your rack's depth)

DRAWER_CLEAR = 0.5                   # per side, drawer box in the sleeve
DRAWER_WALL = 1.6
FRONT_T = 8.0                        # drawer front plate thickness
FRONT_GAP = 0.3                      # between the drawer front and the faceplate when closed
PULL_W, PULL_H, PULL_D = 50.0, 9.0, 4.0   # finger pull pocket under the text
INLAY_T = 1.0                        # text depth (flush inlay)
TEXT_MAX_W, TEXT_MAX_CAP = 196.0, 19.0

PALETTE = ["#2B2F36", "#D7261E", "#F4F4F0"]   # body, "Salsa", "Homelab"
BODY, RED, WHITE = 1, 2, 3


def text_shapes(text1: str, text2: str):
    """Shapely outlines of the two words (DejaVu Sans Bold, bundled with matplotlib), one line, centered.

    Returns (word1, word2) sized to fit TEXT_MAX_W x TEXT_MAX_CAP, cap line centered on y=0.
    """
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath

    fp = FontProperties(family="DejaVu Sans", weight="bold")

    def outline(s: str):
        geo = sg.Polygon()
        for ring in TextPath((0, 0), s, size=100, prop=fp).to_polygons():
            if len(ring) >= 3:
                geo = geo.symmetric_difference(sg.Polygon(ring).buffer(0))
        return geo

    full = outline(f"{text1} {text2}")
    w1 = outline(text1)                     # same start and kerning as the first word of `full`
    w2 = full.difference(w1.buffer(0.01))
    x0, _, x1, _ = full.bounds
    cap = outline("H").bounds[3]
    k = min(TEXT_MAX_W / (x1 - x0), TEXT_MAX_CAP / cap)
    shift = -(x0 + x1) / 2
    out = []
    for g in (w1, w2):
        g = translate(g, shift, -cap / 2)
        out.append(scale(g, k, k, origin=(0, 0)))
    return out[0], out[1], round((x1 - x0) * k, 1), round(cap * k, 1)


def front_xz(shape, y_front: float, depth: float) -> trimesh.Trimesh:
    """Extrude a 2D (x, z) shape from the front face y=y_front back (+Y) by `depth`."""
    m = extrude(shape, 0, depth)
    # 2D (x, z) + extrusion e -> world (x, y_front + e, z): proper rotation (no mirroring)
    m.apply_transform(np.array([[1, 0, 0, 0], [0, 0, 1, y_front], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=float))
    return m


def frame() -> trimesh.Trimesh:
    z0 = (U - SLEEVE_H) / 2
    panel = rounded_panel(-PANEL_W / 2, PANEL_W / 2, 0.79 / 2, 0.79 / 2 + PANEL_H, PANEL_CORNER_R, PANEL_T)
    sleeve_out = box(-SLEEVE_W / 2, SLEEVE_W / 2, PANEL_T - 0.01, PANEL_T + SLEEVE_D, z0, z0 + SLEEVE_H)
    w = SLEEVE_WALL
    inner = box(-SLEEVE_W / 2 + w, SLEEVE_W / 2 - w, -1, PANEL_T + SLEEVE_D + 1, z0 + w, z0 + SLEEVE_H - w)
    centers = np.mean(HOLE_SPAN) / 2
    half_len = (HOLE_SPAN[1] - HOLE_SPAN[0]) / 4 + SLOT_EXTRA / 2
    slots = [slot(s * centers, z, half_len, SLOT_W, PANEL_T) for s in (-1, 1) for z in HOLE_Z]
    return diff(union([panel, sleeve_out]), [inner, *slots])


def drawer(text1: str, text2: str):
    """Drawer parts [(slot, mesh)] in the closed position, plus layout info."""
    z0 = (U - SLEEVE_H) / 2
    zf = z0 + SLEEVE_WALL                           # sleeve floor = drawer bottom
    half_in = SLEEVE_W / 2 - SLEEVE_WALL - DRAWER_CLEAR
    box_h = SLEEVE_H - 2 * SLEEVE_WALL - 2 * DRAWER_CLEAR
    y_front = -FRONT_GAP - FRONT_T                  # front face of the drawer
    y_back = PANEL_T + SLEEVE_D - 2.0
    # Front plate in (x, z): as wide and as high-reaching as the sleeve, its bottom flush with the drawer
    # floor so the drawer prints flat on its bottom. It overlaps the window at the top and sides (the stop).
    r = 3.0
    pz0, pz1 = zf, z0 + SLEEVE_H
    plate = sg.box(-SLEEVE_W / 2 + r, pz0 + r, SLEEVE_W / 2 - r, pz1 - r).buffer(r, quad_segs=12)
    w1, w2, text_w, cap = text_shapes(text1, text2)
    top = unary_union([w1, w2]).bounds[3]
    w1, w2 = translate(w1, 0, pz1 - 3.5 - top), translate(w2, 0, pz1 - 3.5 - top)   # 3.5 mm under the top edge
    pull = sg.box(-PULL_W / 2 + 2, pz0 + 3.0, PULL_W / 2 - 2, pz0 + 3.0 + PULL_H).buffer(2.0, quad_segs=8)
    letters = unary_union([w1, w2])

    plate_back = front_xz(plate, y_front + INLAY_T, FRONT_T - INLAY_T)
    plate_skin = front_xz(plate.difference(letters).difference(pull), y_front, INLAY_T)
    body = union([plate_back, plate_skin])
    body = diff(body, [front_xz(pull, y_front - 1, PULL_D + 1)])
    tray = box(-half_in, half_in, y_front + FRONT_T - 0.01, y_back, zf, zf + box_h)
    cavity = box(-half_in + DRAWER_WALL, half_in - DRAWER_WALL, y_front + FRONT_T, y_back - DRAWER_WALL,
                 zf + DRAWER_WALL, zf + box_h + 1)
    body = drop_slivers(union([body, diff(tray, [cavity])]))
    parts = [(BODY, body), (RED, front_xz(w1, y_front, INLAY_T)), (WHITE, front_xz(w2, y_front, INLAY_T))]
    info = {
        "text_mm": {"width": text_w, "cap_height": cap},
        "drawer_inside_mm": [round(2 * (half_in - DRAWER_WALL), 1),
                             round(y_back - DRAWER_WALL - (y_front + FRONT_T), 1), round(box_h - DRAWER_WALL, 1)],
        "drawer_outside_mm": [round(2 * half_in, 1), round(y_back - y_front, 1), round(box_h, 1)],
        "front_plate_mm": [SLEEVE_W, round(pz1 - pz0, 2), FRONT_T],
        "text_clear_of_pull_mm": round(letters.distance(pull), 2),
        "text_inside_plate": bool(plate.buffer(-2.0).contains(letters)),
        "front_clear_of_rack_slots_mm": round(np.mean(HOLE_SPAN) / 2 - (HOLE_SPAN[1] - HOLE_SPAN[0]) / 4
                                              - SLOT_W / 2 - SLEEVE_W / 2, 2),
        "sleeve_fits_between_rails": bool(SLEEVE_W < OPENING_W),
        "pull_pocket_mm": [PULL_W, PULL_H, PULL_D],
    }
    return parts, info


def overhang(mesh: trimesh.Trimesh) -> float:
    n, c, a = mesh.face_normals, mesh.triangles_center, mesh.area_faces
    over = (n[:, 2] < -np.cos(np.radians(45))) & (c[:, 2] > mesh.bounds[0][2] + 0.05)
    return round(float(a[over].sum()), 1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="1U rack sign with a drawer")
    ap.add_argument("--text1", default="Salsa")
    ap.add_argument("--text2", default="Homelab")
    ap.add_argument("--out", type=Path, default=Path("output/cad-rack-sign"))
    args = ap.parse_args(argv)
    fr = frame()
    parts, info = drawer(args.text1, args.text2)
    dr = union([m for _, m in parts])
    inter = trimesh.boolean.intersection([fr, dr], engine="manifold")
    info["drawer_frame_overlap_mm3"] = round(float(inter.volume), 4) if len(inter.faces) else 0.0
    info["watertight"] = {"frame": bool(fr.is_watertight), **{f"drawer slot {s}": bool(m.is_watertight)
                                                              for s, m in parts}}
    info["frame_extents_mm"] = [round(float(v), 2) for v in fr.extents]

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    # Frame: face-down (+90 deg about X sends the front, -Y, onto the bed).
    to_bed = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
    fr_print = fr.copy().apply_transform(to_bed)
    fr_print.apply_translation(-fr_print.bounds[0] * [0, 0, 1])
    info["frame_print"] = {"footprint_mm": [round(float(v), 1) for v in fr_print.extents[:2]],
                           "height_mm": round(float(fr_print.extents[2]), 1), "overhang_mm2": overhang(fr_print)}
    fr_print.export(out / "frame.stl")
    fr_print.export(out / "frame.3mf")
    # Drawer: upright, floor on the bed.
    zmin = dr.bounds[0][2]
    pr = [(s, m.copy().apply_translation([0, 0, -zmin])) for s, m in parts]
    info["drawer_print"] = {"footprint_mm": [round(float(v), 1) for v in dr.extents[:2]],
                            "height_mm": round(float(dr.extents[2]), 1),
                            "overhang_mm2": overhang(union([m for _, m in pr]))}
    names = {BODY: "drawer", RED: f"text {args.text1}", WHITE: f"text {args.text2}"}
    bambu3mf.write([bambu3mf.Part(names[s], m, s) for s, m in pr], PALETTE, out / "drawer.3mf", name="sign drawer")

    rgb = printprep.hex_to_rgb(PALETTE + ["#3A3F45"])
    tip = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])  # +Z toward the camera: top view
    for name, angle, extra, view in (("front", 0, 0.0, None), ("angled", -35, 0.0, None),
                                     ("open-top", 0, 120.0, tip)):
        meshes = [(3, fr)] + [(s - 1, m.copy().apply_translation([0, -extra, 0])) for s, m in parts]
        if view is not None:
            meshes = [(i, m.copy().apply_transform(view)) for i, m in meshes]
        tri = np.concatenate([m.triangles for _, m in meshes])
        cols = np.concatenate([np.tile(rgb[i], (len(m.faces), 1)) for i, m in meshes])
        printprep.render_colored_faces(tri, cols, out / f"view-{name}.png", "", views=((angle, name),), px_per_mm=4)
    (out / "report.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
