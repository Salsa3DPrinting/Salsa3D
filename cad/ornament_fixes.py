"""Hand fixes to specific Meshy ornament images, applied before tracing (pixel coordinates of those images).

Each fix takes the grayscale PIL image and returns an edited copy. Coordinates were read off the
images in output/ornament-art/<name>/ (896 x 1200 px; ~0.087 mm per px once traced to a 76 mm ball).
"""

from __future__ import annotations

import itertools

import numpy as np
import shapely.geometry as sg
from PIL import Image, ImageDraw
from shapely.affinity import scale

LINE_PX = 14            # stroke width of the art (matches Meshy's lines)


def _draw_outlined(img: Image.Image, shape, width: int = LINE_PX) -> None:
    """Draw a filled shape as a black outline (white inside), `width` px thick, onto img."""
    d = ImageDraw.Draw(img)
    for g in getattr(shape, "geoms", [shape]):
        d.polygon([tuple(p) for p in np.asarray(g.exterior.coords)], fill=0)
    inner = shape.buffer(-width)
    for g in getattr(inner, "geoms", [inner]):
        if not g.is_empty:
            d.polygon([tuple(p) for p in np.asarray(g.exterior.coords)], fill=255)


def gift(img: Image.Image) -> Image.Image:
    """Redraw the lid: symmetric, ribbon running through it, one dot each side, bow tails hang from under it."""
    img = img.copy()
    d = ImageDraw.Draw(img)
    x0, x1, y0, y1 = 188, 710, 500, 634
    d.rectangle((x0 - 4, y0 - 2, x1 + 4, y1), fill=255)                      # clear the old lid
    lid = sg.box(x0, y0, x1, y1).buffer(-12).buffer(12)
    _draw_outlined(img, lid)
    d = ImageDraw.Draw(img)
    for x in (403, 490):                                                         # ribbon across the lid
        d.rectangle((x - LINE_PX // 2, y0, x + LINE_PX // 2, y1), fill=0)
    for cx in (290, 608):                                                        # one dot on each side
        d.ellipse((cx - 17, 567 - 17, cx + 17, 567 + 17), fill=0)
    return img


def _taper(pts, r0: float, r1: float, n: int = 24):
    """A stroke along a polyline that narrows from radius r0 to r1 (hull of circles, so no blobby ends)."""
    line = sg.LineString(pts)
    circles = [line.interpolate(t, normalized=True).buffer(r0 + (r1 - r0) * t, quad_segs=12)
               for t in np.linspace(0, 1, n)]
    return _hull_chain(circles)


def _hull_chain(circles):
    from shapely.ops import unary_union

    return unary_union([a.union(b).convex_hull for a, b in itertools.pairwise(circles)])


def reindeer(img: Image.Image) -> Image.Image:
    """Replace the thin antlers with chunky branching ones a marker can color inside."""
    img = img.copy()
    arr = np.asarray(img).copy()
    h, w = arr.shape
    yy, xx = np.mgrid[0:h, 0:w]
    keep = Image.new("L", (w, h), 0)
    kd = ImageDraw.Draw(keep)
    kd.ellipse((450 - 184, 745 - 244, 450 + 184, 745 + 244), fill=255)              # head with its outline
    ear = [(160, 500), (300, 498), (336, 548), (318, 600), (304, 646), (225, 640), (168, 545)]
    kd.polygon(ear, fill=255)
    kd.polygon([(900 - x, y) for x, y in ear], fill=255)                           # right ear (mirror)
    keep = np.asarray(keep) > 0
    old = (yy > 290) & (yy < 600) & (xx > 200) & (xx < 700) & ~keep
    arr[old] = 255                                                               # erase the old antlers
    img = Image.fromarray(arr)

    def antler(sign: float):
        def p(x, y):
            return (450 + sign * (x - 450), y)
        beam = _taper([p(395, 545), p(350, 460), p(318, 380), p(300, 300)], 46, 36)
        tine_out = _taper([p(345, 450), p(285, 430), p(225, 395)], 42, 32)
        tine_mid = _taper([p(322, 395), p(255, 345)], 40, 32)
        tine_up = _taper([p(314, 360), p(368, 300)], 40, 32)
        return beam.union(tine_out).union(tine_mid).union(tine_up)

    head_poly = scale(sg.Point(450, 745).buffer(1, quad_segs=64), 176, 236, origin=(450, 745))
    for s in (1.0, -1.0):
        shape = antler(s).difference(head_poly).buffer(-8).buffer(8)          # ends on the head outline
        _draw_outlined(img, shape)
    return img


FIXES = {"gift": gift, "reindeer": reindeer}
