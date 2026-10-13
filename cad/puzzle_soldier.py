"""Children's tray puzzle of the Framingham Shoppers World toy soldier.

A board with a soldier-shaped recess, and 8 chunky pieces (hat, head, tunic, two arms, two legs,
rifle). Small color details are printed on top of a piece instead of being separate pieces. The recess
floor is colored like each piece so kids can match colors as well as shapes.

Shapes were traced from the user's straight-on front photo of the soldier (1506x2000 px) and scaled
so the soldier is 8 in (203.2 mm) tall. The figure is widened 1.5x sideways so arms and legs are wide
enough for small hands. Coordinates below are photo pixels; px() converts them to mm
(X centered, Y up from the boot soles).

Run: python -m cad.puzzle_soldier [--out DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import shapely.geometry as sg
import trimesh
from shapely.affinity import translate
from shapely.ops import unary_union

from cad.name_tag import drop_slivers, extrude
from meshy3d import bambu3mf, printprep

# --- Size ---------------------------------------------------------------------------------------
HEIGHT = 203.2                      # 8 in, plume tip to boot soles
TOP_PX, BOTTOM_PX, CENTER_PX = 100, 1815, 709
SCALE = HEIGHT / (BOTTOM_PX - TOP_PX)
WIDEN = 1.5

# --- Puzzle construction -----------------------------------------------------------------------
PIECE_T = 6.0                       # piece thickness
INLAY_T = 0.6                       # colored details on top of pieces
CLEAR = 0.35                        # gap per side between a piece and its neighbours / the wall
PIECE_ROUND = 1.0                   # round the pieces' corners (safer, easier fit)
FLOOR_T = 3.0                       # board floor under the recess
FLOOR_INLAY_T = 0.4                 # colored "picture" in the top of the floor
WALL_H = 5.0                        # recess depth; pieces stand 1 mm proud for easy grabbing
MARGIN = 12.0                       # board border around the soldier
BOARD_R = 8.0
PLATE = 256.0                       # Bambu X1/P1/A1 bed
LAYOUT_GAP = 5.0

PALETTE = ["#8EC3E6", "#D7261E", "#2A3FB0", "#F2D21B", "#F4F4F0", "#F2C9A8", "#1C1C1C", "#7A4A2A"]
BOARD, RED, BLUE, YELLOW, WHITE, SKIN, BLACK, BROWN = range(1, 9)


def px(x: float, y: float) -> tuple[float, float]:
    return ((x - CENTER_PX) * SCALE * WIDEN, (BOTTOM_PX - y) * SCALE)


def poly(*pts) -> sg.Polygon:
    return sg.Polygon([px(*p) for p in pts])


def circle(x, y, r_px) -> sg.Polygon:
    cx, cy = px(x, y)
    return sg.Point(cx, cy).buffer(r_px * SCALE * WIDEN, quad_segs=24)


def band(p0, p1, width_px) -> sg.Polygon:
    """A straight strap between two photo points (e.g. the cross-belts)."""
    return sg.LineString([px(*p0), px(*p1)]).buffer(width_px * SCALE * WIDEN / 2, cap_style="flat")


def pieces() -> list[dict]:
    """Each piece: name, main color, outline, and colored details (clipped to the outline)."""
    hat = unary_union([
        poly((620, 165), (788, 165), (780, 360), (632, 360)),                   # crown + visor
        poly((703, 100), (738, 160), (703, 200), (668, 160)),                    # plume tip above the crown
    ])
    # The yellow collar belongs to the head piece: as a strip on top of the tunic it would be ~3 mm wide.
    head = poly((640, 360), (778, 360), (776, 490), (775, 522), (645, 522), (643, 490))
    tunic = poly((775, 522), (860, 545), (860, 1000), (925, 1195), (515, 1195),
                 (555, 1000), (555, 545), (645, 522))
    arm_l = poly((555, 545), (555, 1000), (497, 1000), (497, 572))
    arm_r = poly((860, 545), (918, 572), (918, 1000), (860, 1000))
    # Legs: the board keeps a strip at least ~4.5 mm wide between them (a wedge tapering to a point
    # at the crotch would be a fragile sliver of wall).
    leg_l = poly((562, 1195), (696, 1195), (672, 1815), (566, 1815))
    leg_r = poly((722, 1195), (880, 1195), (884, 1815), (770, 1815))

    # Rifle: its own lane left of the arm (in the photo it overlaps the arm and hand).
    arm_left_mm = px(497, 0)[0]
    w, gap = 10.0, 4.5
    cx = arm_left_mm - gap - w / 2
    top = px(0, 560)[1]
    stock_top, barrel_top = px(0, 1030)[1], px(0, 820)[1]
    rifle = unary_union([
        sg.box(cx - w / 2 - 1.0, 0, cx + w / 2 + 1.0, 28),                    # wider butt
        sg.box(cx - w / 2, 0, cx + w / 2, stock_top),                          # stock
        sg.box(cx - 3.5, stock_top - 1, cx + 3.5, barrel_top),                 # barrel
        sg.box(cx - 3.0, barrel_top - 1, cx + 3.0, top - 3.0),                 # bayonet
        sg.Point(cx, top - 3.0).buffer(3.0, quad_segs=16),                     # rounded tip
    ])

    return [
        {"name": "hat", "color": BLUE, "shape": hat,
         "details": [(YELLOW, poly((703, 100), (738, 160), (712, 290), (703, 320), (694, 290), (668, 160))),
                     (YELLOW, circle(703, 308, 17))]},
        {"name": "head", "color": SKIN, "shape": head,
         "details": [(BLACK, circle(675, 388, 11)), (BLACK, circle(740, 388, 11)),
                     (BLACK, unary_union([poly((664, 422), (700, 412), (707, 432), (668, 440)),
                                          poly((752, 422), (716, 412), (707, 432), (748, 440))])),
                     (RED, circle(707, 448, 9)),
                     (YELLOW, poly((640, 490), (780, 490), (780, 530), (640, 530)))]},
        {"name": "tunic", "color": RED, "shape": tunic,
         "details": [(WHITE, band((565, 575), (845, 855), 40)), (WHITE, band((850, 575), (570, 855), 40)),
                     (WHITE, poly((555, 850), (860, 850), (860, 900), (555, 900))),
                     *[(YELLOW, circle(710, y, 18)) for y in (655, 790, 960, 1085)]]},
        {"name": "left arm", "color": RED, "shape": arm_l, "details": [(WHITE, poly((497, 900), (555, 900),
                                                                                    (555, 1000), (497, 1000)))]},
        {"name": "right arm", "color": RED, "shape": arm_r, "details": [(WHITE, poly((860, 920), (918, 920),
                                                                                     (918, 1000), (860, 1000)))]},
        {"name": "left leg", "color": BLUE, "shape": leg_l, "details": [(BLACK, poly((560, 1715), (690, 1715),
                                                                                     (690, 1815), (560, 1815)))]},
        {"name": "right leg", "color": BLUE, "shape": leg_r, "details": [(BLACK, poly((760, 1715), (890, 1715),
                                                                                      (890, 1815), (760, 1815)))]},
        {"name": "rifle", "color": BROWN, "shape": rifle,
         "details": [(BLACK, sg.box(cx - w, stock_top, cx + w, barrel_top)),
                     (WHITE, sg.box(cx - w, barrel_top, cx + w, top + 1))]},
    ]


def piece_outline(shape: sg.Polygon) -> sg.Polygon:
    """Inset for clearance, then round the corners."""
    s = shape.buffer(-CLEAR, join_style="mitre")
    return s.buffer(-PIECE_ROUND, join_style="round").buffer(PIECE_ROUND, join_style="round")


def solid_with_details(outline, color: int, details, z0: float, height: float, inlay: float):
    """A piece (or floor) with flush colored details in its top `inlay` mm. Returns [(slot, mesh)]."""
    top = z0 + height
    out: dict[int, list] = {}
    used = sg.Polygon()
    for slot, shape in details:
        region = shape.intersection(outline).difference(used)
        if region.area > 0.05:
            out.setdefault(slot, []).append(region)
            used = used.union(region)
    meshes = [(slot, extrude(unary_union(rs), top - inlay, top)) for slot, rs in out.items()]
    body = [extrude(outline, z0, top - inlay)]
    rest = outline.difference(used)
    if rest.area > 0.05:
        body.append(extrude(rest, top - inlay, top))
    body_mesh = trimesh.boolean.union(body, engine="manifold") if len(body) > 1 else body[0]
    return [(color, body_mesh)] + meshes


def layout(shapes: list[sg.Polygon], x0: float, x1: float, y0: float, y1: float, step: float = 1.0):
    """Bottom-left packing of the real outlines (not boxes), tallest first, LAYOUT_GAP apart.

    Returns one (dx, dy) move per shape so it lands inside [x0, x1] x [y0, y1].
    """
    from shapely.prepared import prep

    order = sorted(range(len(shapes)), key=lambda i: -(shapes[i].bounds[3] - shapes[i].bounds[1]))
    moves: list = [None] * len(shapes)
    placed = sg.Polygon()
    for i in order:
        bx0, by0, bx1, by1 = shapes[i].bounds
        keep_out = prep(placed.buffer(LAYOUT_GAP))
        spot = None
        for x in np.arange(x0, x1 - (bx1 - bx0) + 1e-9, step):
            for y in np.arange(y0, y1 - (by1 - by0) + 1e-9, step):
                if not keep_out.intersects(translate(shapes[i], x - bx0, y - by0)):
                    spot = (x - bx0, y - by0)
                    break
            if spot:
                break
        if spot is None:
            raise ValueError("pieces don't fit on the plate")
        moves[i] = spot
        placed = placed.union(translate(shapes[i], *spot))
    return moves


def board(ps):
    """Board outline, rim (wall) shape, and [(slot, mesh)]: floor with a colored picture + rim walls."""
    silhouette = unary_union([p["shape"] for p in ps])
    sx0, sy0, sx1, sy1 = silhouette.bounds
    outline = sg.box(sx0 - MARGIN + BOARD_R, sy0 - MARGIN + BOARD_R, sx1 + MARGIN - BOARD_R,
                     sy1 + MARGIN - BOARD_R).buffer(BOARD_R, quad_segs=16)
    floor_details = [(p["color"], p["shape"]) for p in ps]
    meshes = solid_with_details(silhouette, BOARD, floor_details, 0, FLOOR_T, FLOOR_INLAY_T)
    rim = outline.difference(silhouette)
    meshes.append((BOARD, extrude(rim, 0, FLOOR_T + WALL_H)))
    return outline, rim, meshes


def assembled():
    """[(slot, mesh)] of the finished puzzle: every piece sitting in its place on the board floor."""
    ps = pieces()
    out = board(ps)[2]
    for p in ps:
        out += solid_with_details(piece_outline(p["shape"]), p["color"], p["details"], FLOOR_T, PIECE_T, INLAY_T)
    return out


def build():
    ps = pieces()
    board_outline, rim, board_parts = board(ps)
    sx0, sy0, sx1, sy1 = unary_union([p["shape"] for p in ps]).bounds

    # Shift everything so the board starts at x=0, y=0 on the plate.
    bx0, by0 = board_outline.bounds[:2]
    shift = np.array([-bx0, -by0, 0])
    board_w = board_outline.bounds[2] - bx0

    outlines = [piece_outline(p["shape"]) for p in ps]
    moves = layout(outlines, bx0 + board_w + 8.0, bx0 + PLATE - 3.0, by0 + 3.0, by0 + PLATE - 3.0)
    by_slot: dict[int, list] = {}
    for slot, m in board_parts:
        by_slot.setdefault(slot, []).append(m.apply_translation(shift))
    piece_meshes = []
    for p, outline, (dx, dy) in zip(ps, outlines, moves):
        o = translate(outline, dx, dy)
        dets = [(s, translate(d, dx, dy)) for s, d in p["details"]]
        parts = solid_with_details(o, p["color"], dets, 0, PIECE_T, INLAY_T)
        for slot, m in parts:
            m.apply_translation(shift)
            by_slot.setdefault(slot, []).append(m)
        piece_meshes.append((p["name"], o, parts))

    names = {BOARD: "board", RED: "red", BLUE: "blue", YELLOW: "yellow", WHITE: "white", SKIN: "skin",
             BLACK: "black", BROWN: "brown"}
    parts = [bambu3mf.Part(names[s], drop_slivers(trimesh.boolean.union(ms, engine="manifold") if len(ms) > 1
                                                  else ms[0]), s) for s, ms in sorted(by_slot.items())]

    info = {
        "soldier_mm": [round(sx1 - sx0, 1), round(sy1 - sy0, 1)],
        "board_mm": [round(board_w, 1), round(board_outline.bounds[3] - by0, 1), FLOOR_T + WALL_H],
        "pieces": {p["name"]: {"bbox_mm": [round(v, 1) for v in (o.bounds[2] - o.bounds[0], o.bounds[3] - o.bounds[1])],
                               "area_thinner_than_4mm_mm2": thin_area(o, 4.0)} for p, o in zip(ps, outlines)},
        "board_wall_area_thinner_than_3mm_mm2": thin_area(rim, 3.0),
        "pieces_overlap_in_tray": overlaps(outlines),
        "piece_count": len(ps),
    }
    return parts, info, ps


def thin_area(shape, width: float) -> float:
    """Area of the parts of `shape` narrower than `width` (what a morphological opening removes).

    Sharp outer corners lose a little area too, so small numbers (a few mm2) are just corners.
    """
    opened = shape.buffer(-width / 2, join_style="round").buffer(width / 2, join_style="round")
    return round(shape.difference(opened).area, 1)


def overlaps(outlines) -> float:
    total = 0.0
    for i, a in enumerate(outlines):
        for b in outlines[i + 1:]:
            total += a.intersection(b).area
    return round(total, 4)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Soldier tray puzzle")
    ap.add_argument("--out", type=Path, default=Path("output/cad-puzzle"))
    args = ap.parse_args(argv)
    parts, info, _ = build()
    allm = trimesh.util.concatenate([p.mesh for p in parts])
    info["plate_mm"] = [round(float(v), 1) for v in allm.extents]
    info["fits_256_plate"] = bool(allm.extents[0] <= PLATE and allm.extents[1] <= PLATE)
    info["parts_watertight"] = {p.name: bool(p.mesh.is_watertight) for p in parts}
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    bambu3mf.write(parts, PALETTE, out / "soldier-puzzle.3mf", name="soldier puzzle")

    # Top-down color render of the plate (board + pieces laid out).
    stand = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
    tri = np.concatenate([p.mesh.copy().apply_transform(stand).triangles for p in parts])
    rgb = printprep.hex_to_rgb(PALETTE)
    cols = np.concatenate([np.tile(rgb[p.filament - 1], (len(p.mesh.faces), 1)) for p in parts])
    printprep.render_colored_faces(tri, cols, out / "plate.png", "Print plate: board and pieces",
                                   views=((0, "Top"),), px_per_mm=4)
    done = assembled()
    tri = np.concatenate([m.copy().apply_transform(stand).triangles for _, m in done])
    cols = np.concatenate([np.tile(rgb[s - 1], (len(m.faces), 1)) for s, m in done])
    printprep.render_colored_faces(tri, cols, out / "assembled.png", "Finished puzzle",
                                   views=((0, "Top"), (-30, "Angled")), px_per_mm=4)
    (out / "report.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
