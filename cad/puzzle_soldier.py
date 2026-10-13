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
from shapely.affinity import scale, translate
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


def band(p0, p1, width_mm) -> sg.Polygon:
    """A straight strap through two photo points, `width_mm` wide (e.g. the cross-belts)."""
    return sg.LineString([px(*p0), px(*p1)]).buffer(width_mm / 2, cap_style="flat")


def extend(p0, p1, y0, y1):
    """The line through photo points p0 and p1, cut at photo rows y0 and y1."""
    (x0, a), (x1, b) = p0, p1
    at = lambda y: (x0 + (x1 - x0) * (y - a) / (b - a), y)
    return at(y0), at(y1)


def stroke(pts, radius, step: float = 0.15) -> sg.Polygon:
    """A brush stroke along a polyline whose half-width goes through `radius` (one value per point)."""
    knots = np.r_[0, np.cumsum(np.hypot(*np.diff(np.asarray(pts), axis=0).T))]
    line = sg.LineString(smooth(pts))  # same ends, rounded bends
    t = knots / knots[-1]
    dots = [line.interpolate(d).buffer(float(np.interp(d / line.length, t, radius)), quad_segs=12)
            for d in np.arange(0, line.length + step, step)]
    return unary_union(dots)


def smooth(pts, rounds: int = 4):
    """Chaikin corner cutting: keeps the end points, rounds every bend."""
    p = np.asarray(pts, dtype=float)
    for _ in range(rounds):
        q = np.empty((2 * len(p) - 2, 2))
        q[0::2] = 0.75 * p[:-1] + 0.25 * p[1:]
        q[1::2] = 0.25 * p[:-1] + 0.75 * p[1:]
        p = np.vstack([p[:1], q, p[-1:]])
    return p


def mirror(pts):
    return [(-x, y) for x, y in pts]


def face() -> list[tuple[int, sg.Polygon]]:
    """Eyebrows, eyes, handlebar mustache and open mouth, traced from the photo's face.

    Drawn in mm (x from the face's center line, y down from the top of the head) instead of photo
    pixels so the 1.5x widening doesn't stretch them, and so no line is thinner than ~1 mm (thinner
    lines don't print with a 0.4 mm nozzle).
    """
    top = px(0, 360)[1]

    def f(pts):
        return [(x, top - y) for x, y in pts]

    brow = [(-9.6, 3.4), (-8.2, 2.0), (-6.0, 1.5), (-3.8, 1.9), (-2.4, 2.9)]
    brows = unary_union([sg.LineString(f(b)).buffer(0.55, quad_segs=8) for b in (brow, mirror(brow))])
    eye_white = sg.Point(0, 0).buffer(1.0, quad_segs=24)
    whites = unary_union([translate(scale(eye_white, 3.0, 1.6, origin=(0, 0)), x, top - 4.2) for x in (-5.8, 5.8)])
    # Pupils up against the top of the eye (as in the photo): no white sliver too thin to print above them.
    pupils = unary_union([sg.Point(x, top - 3.75).buffer(1.15, quad_segs=24) for x in (-5.8, 5.8)]).intersection(whites)
    # Handlebar mustache: a brush stroke along a curve, thickest mid-cheek, curling up at the tips,
    # with a small notch at the center where the two halves meet.
    path = [(-0.4, 7.3), (-2.0, 7.5), (-4.0, 8.0), (-6.0, 8.1), (-7.9, 7.6), (-9.1, 6.7), (-9.2, 5.6), (-8.4, 5.3)]
    radius = [0.75, 0.9, 1.0, 0.9, 0.75, 0.6, 0.5, 0.5]
    mustache = unary_union([stroke(f(pts), radius) for pts in (path, mirror(path))])
    lips = [(-2.8, 8.4), (2.8, 8.4), (2.5, 9.9), (1.4, 10.9), (0, 11.4), (-1.4, 10.9), (-2.5, 9.9)]
    teeth = sg.Polygon(f(lips)).intersection(sg.box(-5, top - 9.4, 5, top - 8.0))  # full width: no thin red
    return [(BLACK, brows), (BLACK, pupils), (WHITE, whites), (BLACK, mustache), (WHITE, teeth),
            (RED, sg.Polygon(f(lips)))]


def pieces() -> list[dict]:
    """Each piece: name, main color, outline, and colored details (clipped to the outline).

    Where details overlap, the first one listed wins.
    """
    plume = unary_union([poly((703, 100), (722, 125), (738, 160), (728, 220), (712, 300), (694, 300), (678, 220),
                              (668, 160), (684, 125)),
                         circle(703, 305, 16)])                                  # round knob at the bottom
    hat = unary_union([
        poly((618, 165), (788, 165), (778, 360), (632, 360)),                   # crown + band
        plume.intersection(sg.box(-50, px(0, 170)[1], 50, 300)),                # plume tip above the crown
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

    # Cross-belts: from over each shoulder down to the waist belt (traced centerlines, extended past
    # both ends so the clip to each piece's outline and the belt decide where they stop). They run
    # across the arm pieces' shoulders too, so they line up when the puzzle is done.
    belt = poly((480, 850), (940, 850), (940, 900), (480, 900))
    straps = unary_union([band(*extend((560, 560), (812, 850), 480, 875), 4.6),
                          band(*extend((885, 560), (610, 850), 480, 875), 4.6)])
    buttons = [circle(710, y, 18) for y in (655, 800, 960, 1088)]
    buttons.append(sg.Point(px(709, 552)).buffer(1.6, quad_segs=16))          # small one under the collar
    return [
        {"name": "hat", "color": BLUE, "shape": hat,
         "details": [(YELLOW, plume),
                     (YELLOW, poly((630, 322), (646, 322), (646, 346), (630, 346))),    # band corner tabs
                     (YELLOW, poly((764, 322), (780, 322), (780, 346), (764, 346)))]},
        {"name": "head", "color": SKIN, "shape": head,
         "details": [*face(), (YELLOW, poly((630, 490), (790, 490), (790, 530), (630, 530)))]},
        {"name": "tunic", "color": RED, "shape": tunic,
         "details": [(WHITE, belt), (WHITE, straps), *[(YELLOW, b) for b in buttons]]},
        {"name": "left arm", "color": RED, "shape": arm_l,
         "details": [(WHITE, straps), (WHITE, poly((480, 900), (570, 900), (570, 1010), (480, 1010)))]},
        {"name": "right arm", "color": RED, "shape": arm_r,
         "details": [(WHITE, straps), (WHITE, poly((850, 920), (930, 920), (930, 1010), (850, 1010)))]},
        {"name": "left leg", "color": BLUE, "shape": leg_l, "details": [(BLACK, poly((550, 1715), (700, 1715),
                                                                                     (700, 1830), (550, 1830)))]},
        {"name": "right leg", "color": BLUE, "shape": leg_r, "details": [(BLACK, poly((750, 1715), (900, 1715),
                                                                                      (900, 1830), (750, 1830)))]},
        {"name": "rifle", "color": BROWN, "shape": rifle,
         "details": [(BLACK, sg.box(cx - w, stock_top, cx + w, barrel_top)),
                     (WHITE, sg.box(cx - w, barrel_top, cx + w, top + 10))]},
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
    # The floor shows the whole picture (details too), each piece's art clipped to its own spot.
    floor_details = [(c, d.intersection(p["shape"])) for p in ps for c, d in [*p["details"], (p["color"], p["shape"])]]
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
