"""Color-in tree ornaments: a thin white back with a slightly raised black outline drawing.

Same build as the user's reference ornaments (measured from their 3MF: ~76 x 88 mm, 1.0 mm back,
0.4 mm raised lines). Designs are our own line art, drawn here in mm (origin at the ornament's center,
+Y up). Every white area is checked so a marker tip fits in it (see `check`).

Run: python -m cad.coloring_ornaments mock [--out DIR]     # mock-up sheets to approve
     python -m cad.coloring_ornaments build NAME... [--out DIR]   # 3MF per approved design
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import shapely.geometry as sg
from shapely.affinity import rotate, scale, translate
from shapely.ops import unary_union

BACK_T = 1.0                 # white back
LINE_T = 0.4                 # black lines raised above the back
LW = 1.6                     # line width (4 passes of a 0.4 mm nozzle)
RIM_W = 2.4                  # outer rim
R = 38.0                     # body radius (76 mm ornament body)
HOLE_R = 2.5                 # hanging hole (fits ribbon or an ornament hook)
MARKER_D = 4.0               # every white area must hold a circle this big (marker tip gets in)
REACH_D = 3.0                # ...and most of it must be reachable by a tip this size
REACH_MIN = 0.6             # star points and similar corners can stay a bit out of reach

WHITE, BLACK = "#F4F4F0", "#1C1C1C"


# --- drawing helpers (all return shapely geometry in mm) ------------------------------------------
def line(*pts, w: float = LW):
    return sg.LineString(pts).buffer(w / 2, quad_segs=8)


def loop(*pts, w: float = LW):
    return sg.LinearRing(pts).buffer(w / 2, quad_segs=8)


def ring(c, r, w: float = LW):
    return sg.Point(c).buffer(r + w / 2, quad_segs=32).difference(sg.Point(c).buffer(r - w / 2, quad_segs=32))


def dot(c, r):
    return sg.Point(c).buffer(r, quad_segs=24)


def arc(c, r, a0, a1, w: float = LW, n: int = 40):
    t = np.radians(np.linspace(a0, a1, n))
    return line(*zip(c[0] + r * np.cos(t), c[1] + r * np.sin(t)), w=w)


def outline(shape, w: float = LW):
    """The boundary of a filled shape as a line of width w (centered on the boundary)."""
    polys = [g for g in getattr(shape, "geoms", [shape]) if isinstance(g, (sg.Polygon, sg.MultiPolygon))]
    return unary_union([g.boundary.buffer(w / 2, quad_segs=8) for g in polys if not g.is_empty])


def star_pts(c, r_out, r_in, n=5, rot=90.0):
    pts = []
    for i in range(2 * n):
        r = r_out if i % 2 == 0 else r_in
        a = np.radians(rot + 180.0 * i / n)
        pts.append((c[0] + r * np.cos(a), c[1] + r * np.sin(a)))
    return pts


def glyph(ch: str, c, height: float):
    """A filled text glyph (DejaVu Sans Bold), centered at c, `height` tall."""
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath

    geo = sg.Polygon()
    for r in TextPath((0, 0), ch, size=100, prop=FontProperties(family="DejaVu Sans", weight="bold")).to_polygons():
        if len(r) >= 3:
            geo = geo.symmetric_difference(sg.Polygon(r).buffer(0))
    x0, y0, x1, y1 = geo.bounds
    k = height / (y1 - y0)
    return translate(scale(geo, k, k, origin=(0, 0)), c[0] - (x0 + x1) / 2 * k, c[1] - (y0 + y1) / 2 * k)


# --- frames: the ornament's outer shape (white back) and its fixed lines --------------------------
def bauble():
    """Classic ball ornament: round body, ridged cap and a hanging loop (Christmas)."""
    body = dot((0, 0), R)
    cap = sg.box(-10, R - 3, 10, R + 8).buffer(1.5, quad_segs=6)
    loop_outer = dot((0, R + 12.5), 5.5)
    back = unary_union([body, cap, loop_outer]).difference(dot((0, R + 12.5), HOLE_R))
    lines = unary_union([
        outline(back, RIM_W).intersection(back),
        line((-10.5, R - 1), (10.5, R - 1)),                       # cap meets the ball
        *[line((x, R + 1), (x, R + 7.5)) for x in (-5, 0, 5)],     # cap ridges
        outline(dot((0, R + 12.5), HOLE_R), LW).intersection(back),
    ])
    return back, lines


def medallion():
    """Round ornament with a plain hanging tab (Hanukkah / winter)."""
    body = dot((0, 0), R)
    tab = sg.box(-7, R - 4, 7, R + 9).buffer(2.0, quad_segs=6)
    back = unary_union([body, tab]).difference(dot((0, R + 4.5), HOLE_R))
    lines = unary_union([outline(back, RIM_W).intersection(back),
                         outline(dot((0, R + 4.5), HOLE_R), LW).intersection(back),
                         arc((0, 0), R - 1.2, 60, 120, w=RIM_W)])   # closes the tab off from the body
    return back, lines


# --- designs: each returns (back, lines) ----------------------------------------------------------
def christmas_tree():
    back, frame = bauble()
    tiers = [(0, 21), (-10, 9), (-5.5, 9), (-16, -3), (-10.5, -3), (-24, -17), (24, -17), (10.5, -3), (16, -3),
             (5.5, 9), (10, 9)]
    art = [loop(*tiers), loop((-5, -17), (-5, -26), (5, -26), (5, -17)),
           loop(*star_pts((0, 26.5), 9.5, 4.8)),
           *[dot(c, 1.6) for c in ((-5, 3), (5, 6), (-10, -9), (2, -6), (12, -12), (-3, -14))],
           line((-7, 0), (8, 3)), line((-15, -12), (14, -7))]                  # garlands
    return back, unary_union([frame, *art]).intersection(back)

def gift_box():
    back, frame = bauble()
    art = [loop((-21, -24), (21, -24), (21, 6), (-21, 6)),        # box
           loop((-24, 6), (24, 6), (24, 14), (-24, 14)),           # lid
           line((0, -24), (0, 14)),                                  # ribbon down the middle
           loop((0, 14), (-14, 26), (-17, 19), (-6, 14)),          # bow loops
           loop((0, 14), (14, 26), (17, 19), (6, 14)),
           dot((0, 15.5), 2.6),
           *[dot(c, 1.5) for c in ((-12, -8), (11, -14), (-9, -19), (13, -2), (-15, 0))]]   # polka dots
    return back, unary_union([frame, *art]).intersection(back)


def reindeer():
    back, frame = bauble()
    head = sg.Polygon([(-12, 14), (12, 14), (14, 4), (9, -14), (5, -21), (-5, -21), (-9, -14), (-14, 4)]).buffer(
        3, quad_segs=8)
    ear_l = sg.Polygon([(-12, 12), (-23, 16), (-15, 7)]).buffer(1.5)
    ear_r = scale(ear_l, -1, 1, origin=(0, 0))
    antler = [line((-6, 17), (-10, 27), (-16, 31)), line((-9, 24), (-4, 30)), line((-13, 29), (-15, 34))]
    antlers = antler + [scale(a, -1, 1, origin=(0, 0)) for a in antler]
    art = [outline(unary_union([head, ear_l, ear_r])), *antlers,
           dot((-6, 4), 2.0), dot((6, 4), 2.0),                                      # eyes
           ring((0, -13), 5.5)]                                                       # big round nose
    return back, unary_union([frame, *art]).intersection(back)

def stocking():
    back, frame = bauble()
    sock = sg.Polygon([(-9, 24), (9, 24), (9, -6), (2, -20), (-10, -26), (-20, -24), (-23, -16), (-14, -10),
                       (-9, -4)]).buffer(2.5, quad_segs=8)
    cuff = sg.box(-12, 17, 12, 28).buffer(1.5)
    art = [outline(unary_union([sock, cuff])), line((-12, 17), (12, 17)),
           line((-10, -18), (-4, -24)),                                   # toe patch
           line((4, -6), (9.5, -6)), line((4, -6), (1, -13)),             # heel patch
           loop(*star_pts((-1, 5), 7.5, 3.8))]
    return back, unary_union([frame, *art]).intersection(back)


def menorah():
    back, frame = medallion()
    pitch, w = 6.4, 6.4
    xs = [pitch * (i - 4) for i in range(9)]
    art = [line((xs[0] - w / 2, 0), (xs[-1] + w / 2, 0)),                   # candle holder bar
           line((0, 0), (0, -20)), loop((-12, -20), (12, -20), (8, -27), (-8, -27))]   # stem and base
    for x in xs:
        bottom = 5.0 if x == 0 else 0.0                                     # the shamash stands taller
        if x == 0:
            art.append(loop((-w / 2, 0), (w / 2, 0), (w / 2, bottom), (-w / 2, bottom)))
        art.append(loop((x - w / 2, bottom), (x + w / 2, bottom), (x + w / 2, bottom + 11), (x - w / 2, bottom + 11)))
        f = bottom + 11.8
        flame = sg.Point(x, f + 3.4).buffer(3.1, quad_segs=16).union(
            sg.Polygon([(x - 2.6, f + 4.8), (x, f + 10.5), (x + 2.6, f + 4.8)]))
        art.append(outline(flame))
    return back, unary_union([frame, *art]).intersection(back)

def dreidel():
    back, frame = medallion()
    body = sg.Polygon([(-15, 14), (15, 14), (15, -6), (0, -26), (-15, -6)]).buffer(2, quad_segs=6)
    handle = sg.box(-3.5, 14, 3.5, 27).buffer(1.2)
    art = [outline(unary_union([body, handle])), line((-16, 14), (16, 14)),
           glyph("ש", (0, 2), 15.0),
           arc((24, 18), 5, 200, 340), arc((-24, -18), 5, 20, 160)]       # little spin swooshes
    return back, unary_union([frame, *art]).intersection(back)


def star_of_david():
    back, frame = medallion()
    t1 = sg.Polygon([(0, 27), (23.4, -13.5), (-23.4, -13.5)])
    t2 = scale(t1, 1, -1, origin=(0, 0))
    art = [outline(t1), outline(t2), ring((0, 0), 8)]
    return back, unary_union([frame, *art]).intersection(back)


def gelt():
    """Chocolate coins (gelt), each stamped with a dreidel letter."""
    back, frame = medallion()
    art = []
    for c, ch in (((-13.5, -9), "נ"), ((13.5, -9), "ג"), ((0, 13), "ה")):
        art += [ring(c, 12.5), glyph(ch, c, 9.0)]
    return back, unary_union([frame, *art]).intersection(back)

def snowflake():
    back, frame = medallion()
    art = [dot((0, 0), 3.0)]
    for k in range(6):
        a = 60 * k
        arm = [line((0, 0), (0, 29)), line((0, 12), (-7, 19)), line((0, 12), (7, 19)),
               line((0, 21), (-5, 26)), line((0, 21), (5, 26))]
        art += [rotate(g, a, origin=(0, 0)) for g in arm]
    return back, unary_union([frame, *art]).intersection(back)


def mitten():
    back, frame = medallion()
    hand = sg.Polygon([(-13, -12), (-14, 10), (-9, 22), (2, 25), (11, 18), (13, 6), (13, -12)]).buffer(2.5)
    thumb = sg.Polygon([(12, 2), (22, 8), (24, 0), (13, -8)]).buffer(2.5)
    cuff = sg.box(-16, -25, 16, -12).buffer(1.5)
    art = [outline(unary_union([hand, thumb, cuff])), line((-15.5, -12), (15.5, -12)),
           *[line((x, -23), (x, -14)) for x in (-9, -3, 3, 9)],                           # cuff ribs
           ring((-1, 6), 6.5), *[line((-1, 6), (-1 + 6.5 * np.cos(a), 6 + 6.5 * np.sin(a)))
                                  for a in np.radians([90, 210, 330])]]                    # little snowflake
    return back, unary_union([frame, *art]).intersection(back)


def cocoa():
    back, frame = medallion()
    mug = sg.Polygon([(-16, 8), (12, 8), (10, -22), (-14, -22)]).buffer(2)
    handle = sg.Point(13, -6).buffer(11, quad_segs=24).difference(sg.Point(13, -6).buffer(4.5, quad_segs=24))
    handle = handle.difference(mug)
    mallows = [sg.box(x - 4.5, 10, x + 4.5, 17).buffer(1.5, quad_segs=6).intersection(sg.box(x - 7, 10, x + 7, 30))
               for x in (-8, 3)]
    art = [outline(mug), outline(handle), *[outline(m) for m in mallows],
           *[line(*[(x + 2.2 * np.sin(t), 21 + t * 2.0) for t in np.linspace(0, 5, 20)]) for x in (-9, 0, 9)],
           loop(*[(-2 + 5 * np.cos(a) * abs(np.cos(a)) ** 0.2, -7 + 4 * np.sin(a) + 3 * abs(np.cos(a)))
                  for a in np.linspace(0, 2 * np.pi, 60, endpoint=False)])]               # heart on the mug
    return back, unary_union([frame, *art]).intersection(back)

def penguin():
    back, frame = medallion()
    body = scale(sg.Point(0, -8).buffer(1, quad_segs=32), 15, 19, origin=(0, -8))
    head = sg.Point(0, 13).buffer(12, quad_segs=32)
    silhouette = unary_union([body, head])
    belly = scale(sg.Point(0, -12).buffer(1, quad_segs=32), 9.5, 12, origin=(0, -12))
    scarf = sg.box(-20, -0.5, 20, 6.3).intersection(silhouette)
    art = [outline(silhouette), outline(belly), outline(scarf),
           dot((-4.5, 16), 1.8), dot((4.5, 16), 1.8),
           outline(sg.Polygon([(-4.5, 12.5), (4.5, 12.5), (0, 6.6)])),                     # beak
           arc((0, 13), 13.5, 20, 160),                                                    # earmuff band
           dot((-12.6, 13), 3.6), dot((12.6, 13), 3.6),
           line((-14, -7), (-21, -17)), line((14, -7), (21, -17)),                         # flippers
           outline(scale(sg.Point(-6, -28).buffer(1, quad_segs=24), 5.5, 3.2, origin=(-6, -28))),   # feet
           outline(scale(sg.Point(6, -28).buffer(1, quad_segs=24), 5.5, 3.2, origin=(6, -28)))]
    return back, unary_union([frame, *art]).intersection(back)

def soldier():
    """The Framingham Shoppers World soldier, simplified for coloring; the ornament is his silhouette.

    Proportions follow the user's photo (tall plumed hat, red tunic with white cross belts and belt, blue
    trousers, black boots, rifle at his right side) with every color area at least marker-tip wide.
    """
    boots_l, boots_r = sg.box(-13, 0, -2, 8), sg.box(2, 0, 13, 8)
    leg_l, leg_r = sg.box(-12.5, 8, -2, 44), sg.box(2, 8, 12.5, 44)
    tunic = sg.Polygon([(-17, 42), (17, 42), (13, 60), (13, 84), (6, 86), (-6, 86), (-13, 84), (-13, 60)])
    arm_l, arm_r = sg.box(-19.5, 54, -13, 84), sg.box(13, 54, 19.5, 84)
    head = sg.box(-8, 86, 8, 101)
    hat = sg.Polygon([(-9.5, 101), (9.5, 101), (10.5, 115), (-10.5, 115)])
    plume = sg.Polygon([(0, 105), (4.5, 113), (0, 122), (-4.5, 113)])
    stock = sg.box(-26, 0, -20, 30)
    barrel = sg.box(-24.4, 29, -21.6, 72)
    bayonet = sg.Polygon([(-23.6, 71), (-22.4, 71), (-23, 82)]).buffer(0.5)
    base = sg.box(-28, -6, 16, 0.5).buffer(2.0, quad_segs=6).intersection(sg.box(-40, -8, 40, 0.5))
    hang = sg.box(-3, 120, 3, 126)
    parts = [boots_l, boots_r, leg_l, leg_r, tunic, arm_l, arm_r, head, hat, plume, stock, base, hang]
    back = unary_union([*parts, barrel, bayonet, dot((0, 127), 4.5)]).difference(dot((0, 127), 2.0))
    belt = sg.box(-13, 63, 13, 69.5)
    straps = unary_union([line((-12, 83), (9, 69.5), w=5.2), line((12, 83), (-9, 69.5), w=5.2)]).intersection(
        tunic).difference(belt)
    art = [outline(back, RIM_W).intersection(back),
           *[outline(g) for g in (boots_l, boots_r, leg_l, leg_r, tunic, arm_l, arm_r, head, hat, stock, base)],
           outline(plume), outline(belt), outline(straps),
           line((-19.5, 61), (-13, 61)), line((13, 61), (19.5, 61)),                       # gloves
           line((-8, 89.5), (8, 89.5)),                                                    # collar
           line((-9.6, 104.5), (9.6, 104.5)),                                              # hat band
           barrel, bayonet,
           dot((-3.5, 96.5), 1.2), dot((3.5, 96.5), 1.2),                                  # eyes
           line((-4.5, 93), (-1, 94), (1, 94), (4.5, 93), w=1.4),                          # mustache
           *[dot((0, y), 1.4) for y in (49, 56, 78)],                                      # buttons
           outline(dot((0, 127), 2.0))]
    return back, unary_union(art).intersection(back)

DESIGNS = {
    "christmas": {"christmas-tree": christmas_tree, "gift": gift_box, "reindeer": reindeer, "stocking": stocking},
    "hanukkah": {"menorah": menorah, "dreidel": dreidel, "star-of-david": star_of_david, "gelt": gelt},
    "winter": {"snowflake": snowflake, "mitten": mitten, "cocoa": cocoa, "penguin": penguin},
    "framingham": {"soldier": soldier},
}


def all_designs():
    return {n: f for group in DESIGNS.values() for n, f in group.items()}


# --- checks ---------------------------------------------------------------------------------------
def white_regions(back, lines):
    w = back.difference(lines)
    return [g for g in getattr(w, "geoms", [w]) if g.area > 0.01]


def check(back, lines) -> dict:
    """Every white area must hold a MARKER_D circle, and REACH_MIN of it must be reachable by a REACH_D tip.

    Areas that fail are listed (center and size) so the drawing can be fixed.
    """
    bad = []
    regions = white_regions(back, lines)
    for g in regions:
        fits = not g.buffer(-MARKER_D / 2).is_empty
        reach = g.buffer(-REACH_D / 2).buffer(REACH_D / 2).area / g.area
        if not fits or reach < REACH_MIN:
            c = g.representative_point()
            bad.append({"at_mm": [round(c.x, 1), round(c.y, 1)], "area_mm2": round(g.area, 1),
                        "marker_fits": fits, "reachable": round(reach, 2)})
    x0, y0, x1, y1 = back.bounds
    return {"size_mm": [round(x1 - x0, 1), round(y1 - y0, 1)], "white_areas": len(regions), "too_small": bad}


# --- mock-ups ---------------------------------------------------------------------------------------
def _patches(geom, **kw):
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MPath

    out = []
    for p in getattr(geom, "geoms", [geom]):
        if p.is_empty:
            continue
        verts, codes = [], []
        for ringc in [p.exterior, *p.interiors]:
            xy = np.asarray(ringc.coords)
            verts += xy.tolist()
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(xy) - 2) + [MPath.CLOSEPOLY]
        out.append(PathPatch(MPath(verts, codes), **kw))
    return out


def mock(out: Path) -> dict:
    """One 'photo' sheet per theme: ornaments lying on a wood table, with a soft shadow."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    report = {}
    rng = np.random.default_rng(3)
    for theme, group in DESIGNS.items():
        n = len(group)
        cols = min(n, 2 if n == 4 else n)
        rows = int(np.ceil(n / cols))
        cell_w, cell_h = 100, 135 if theme == "framingham" else 110
        W, H = cols * cell_w + 20, rows * cell_h + 30
        fig = plt.figure(figsize=(W / 25, H / 25), dpi=110)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, W)
        ax.set_ylim(0, H)
        ax.axis("off")
        # wood: warm base with streaks
        ax.add_patch(plt.Rectangle((0, 0), W, H, color="#B98A5A", zorder=0))
        for y in np.linspace(0, H, 70):
            ax.plot([0, W], [y + rng.normal(0, 1.5), y + rng.normal(0, 1.5)], color="#A7774A",
                    lw=rng.uniform(0.3, 1.6), alpha=0.35, zorder=0)
        for i, (name, fn) in enumerate(group.items()):
            back, lines = fn()
            report[name] = check(back, lines)
            cx = 10 + cell_w * (i % cols) + cell_w / 2
            cy = H - 15 - cell_h * (i // cols) - cell_h / 2
            bx0, by0, bx1, by1 = back.bounds
            dx, dy = cx - (bx0 + bx1) / 2, cy - (by0 + by1) / 2
            for p in _patches(translate(back, dx + 1.5, dy - 1.5), color="black", alpha=0.25, lw=0, zorder=1):
                ax.add_patch(p)
            for p in _patches(translate(back, dx, dy), color=WHITE, lw=0, zorder=2):
                ax.add_patch(p)
            for p in _patches(translate(lines, dx, dy), color=BLACK, lw=0, zorder=3):
                ax.add_patch(p)
        out.mkdir(parents=True, exist_ok=True)
        fig.savefig(out / f"mock-{theme}.png")
        plt.close(fig)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Color-in tree ornaments")
    ap.add_argument("cmd", choices=["mock", "build"])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--out", type=Path, default=Path("output/cad-ornaments"))
    args = ap.parse_args(argv)
    if args.cmd == "mock":
        report = mock(args.out)
        (args.out / "mock-report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        return 0
    raise SystemExit("build: pick designs after the mock-ups are approved")


if __name__ == "__main__":
    raise SystemExit(main())
