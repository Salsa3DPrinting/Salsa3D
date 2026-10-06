"""Parametric duct adapter between two fittings, e.g. a fan flange to a PVC pipe spigot.

Coordinates: mm, Z = airflow axis. The first fitting sits on the bed at z = 0 (a fan flange prints face
down, no supports); the transition cone and the second fitting rise above it.

Fittings are given as text specs:
- Fans, by key in FANS:                       "bfs-i06"
- PVC pipe, size + schedule + spigot/socket:  "pvc-4-sch40-spigot", "4in sch40 pvc socket", "1-1/2 sch 40 pvc spigot"
  spigot = the adapter end goes INTO a PVC fitting's socket (it replaces a piece of pipe).
  socket = the adapter end slips OVER a PVC pipe, which stops on an inner ledge.

Where the numbers come from:
- BFS-i06 fan: the user's drawing plus answers (120 mm square frame, R15 corners, 75 mm deep, 4 x Ø12 holes
  at 90 deg on a Ø138 circle, Ø100 air opening). The motor hub plate (7.9 mm proud on one face) has an
  unknown diameter; 70 mm is the user's working assumption.
- PVC pipe OD: standard NPS outside diameters (ASTM D1785), e.g. 4" = 4.500 in.
- PVC socket depth: ASTM D2466 Schedule 40 fittings as listed in Charlotte Pipe's Sch 40 submittal
  (4": entrance 4.518 in, bottom 4.491 in, +/-0.009, depth 2.000 in). Sch 80 fittings (D2467) are not
  in the table yet.
Change the constants below to correct any of them.

Run: python -m cad.adapter bfs-i06 pvc-4-sch40-spigot [--out DIR] [--taper-deg 15]
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

import numpy as np
import shapely.geometry as sg
import trimesh

from meshy3d import printprep

IN = 25.4

# --- General adapter settings ------------------------------------------------------------------
WALL = 3.5               # duct and pipe-end wall thickness
FLANGE_T = 10.0          # fan flange plate thickness (the user's tri-clamp adapter used ~9.5)
TAPER_HALF_ANGLE = 15.0  # cone half-angle in degrees; smaller = gentler (7 deg is a classic diffuser)
SECTIONS = 256           # facets around the circle
BOLT_ACCESS = 30.0       # clear height above the flange for bolt heads / nuts and a socket wrench
BOLT_KEEPOUT_D = 24.0    # keep-out circle around each bolt (fits an M10 hex head plus a socket wrench)
HUB_CLEARANCE = 1.0      # radial clearance around the fan's motor hub plate

# PVC fit: printed parts come out slightly oversize, and the D2466 socket bottom (4.491 in for 4") is
# smaller than the pipe OD (4.500 in) because cemented joints are an interference fit. PLA is not
# cemented, so the spigot is made a little under the pipe OD. Print the fit-test rings to tune this.
SPIGOT_DIAMETRAL_ALLOWANCE = -0.3   # spigot OD = pipe OD + this
SPIGOT_EXTRA = 0.25 * IN             # spigot longer than the socket depth, so the fitting never hits the neck
SPIGOT_CHAMFER = 1.0                 # lead-in chamfer on the spigot tip
SOCKET_DIAMETRAL_CLEARANCE = 0.5     # socket ID = pipe OD + this (slip fit over the pipe)
SOCKET_STOP = 4.0                    # radial width of the ledge the pipe stops on
FIT_TEST_RING_H = 12.0
FIT_TEST_ALLOWANCES = (-0.1, -0.3, -0.5)

# Build volumes (X, Y, Z) of the user's printers, mm.
PRINTERS = {"Bambu Lab P1S": (256, 256, 256), "Bambu Lab H2D": (350, 320, 325)}


@dataclass(frozen=True)
class Fan:
    name: str
    frame: float           # square frame side
    corner_r: float
    depth: float
    bolt_circle_d: float
    hole_d: float
    hole_angles: tuple[float, ...]   # degrees, 0 = +X
    bore_d: float          # air opening on the frame face
    hub_d: float           # motor hub plate diameter (proud of one face)
    hub_proud: float


FANS = {
    "bfs-i06": Fan("BFS-i06 120 x 75 mm fan", frame=120.0, corner_r=15.0, depth=75.0, bolt_circle_d=138.0,
                   hole_d=12.0, hole_angles=(45.0, 135.0, 225.0, 315.0), bore_d=100.0, hub_d=70.0,
                   hub_proud=7.9),
}

# Nominal size (inches) -> pipe OD (inches), ASTM D1785 / NPS.
PIPE_OD_IN = {0.5: 0.840, 0.75: 1.050, 1.0: 1.315, 1.25: 1.660, 1.5: 1.900, 2.0: 2.375, 2.5: 2.875,
              3.0: 3.500, 4.0: 4.500, 6.0: 6.625, 8.0: 8.625}
# Nominal size -> Schedule 40 socket depth (inches), ASTM D2466 per Charlotte Pipe's submittal.
SCH40_SOCKET_DEPTH_IN = {0.5: 0.688, 0.75: 0.719, 1.0: 0.875, 1.25: 0.938, 1.5: 1.094, 2.0: 1.156, 2.5: 1.750,
                         3.0: 1.875, 4.0: 2.000, 6.0: 3.000, 8.0: 4.000}


@dataclass
class End:
    """One fitting. Profiles are (r, z) points measured from this end's face (s = 0) toward the transition."""
    label: str
    kind: str                      # "fan" | "spigot" | "socket"
    length: float                  # along the axis
    join_inner_r: float            # duct inner radius where the transition attaches
    outer: list[tuple[float, float]]
    inner: list[tuple[float, float]]
    info: dict = field(default_factory=dict)
    fan: Fan | None = None


def parse_size(text: str) -> float:
    """'4', '1-1/2', '1 1/2', '1.5', '3/4' -> inches."""
    text = text.strip().replace(" ", "-")
    if "-" in text and "/" in text:
        whole, frac = text.split("-", 1)
        return float(int(whole) + Fraction(frac))
    return float(Fraction(text))


def parse_fitting(spec: str) -> End:
    s = spec.lower().strip().replace('"', "in ")
    key = s.removeprefix("fan-").removeprefix("fan ")
    if key in FANS:
        return fan_end(FANS[key])
    if "pvc" in s:
        style = re.search(r"\b(spigot|socket)\b", s.replace("-", " "))
        sched = re.search(r"sch(?:edule)?[\s-]*(\d+)", s)
        if not style or not sched:
            raise ValueError(f"{spec!r}: PVC spec needs a schedule and spigot/socket, e.g. 'pvc-4-sch40-spigot'")
        rest = s[:sched.start()] + " " + s[sched.end():]
        rest = re.sub(r"pvc|spigot|socket|inches|inch|in\b", " ", rest)
        size_txt = " ".join(t for t in re.split(r"[\s-]+", rest) if t)
        try:
            size = parse_size(size_txt)
        except (ValueError, ZeroDivisionError):
            raise ValueError(f"{spec!r}: could not read a pipe size from {size_txt!r}") from None
        if size not in PIPE_OD_IN:
            raise ValueError(f"{spec!r}: no PVC data for {size} in; known sizes: {sorted(PIPE_OD_IN)}")
        if sched.group(1) != "40":
            raise ValueError(f"{spec!r}: only Schedule 40 socket depths are in the table so far")
        return pvc_end(size, style.group(1))
    raise ValueError(f"Unknown fitting {spec!r}. Fans: {sorted(FANS)}; PVC like 'pvc-4-sch40-spigot'.")


def fan_end(fan: Fan) -> End:
    r = fan.bore_d / 2
    return End(fan.name, "fan", FLANGE_T, r, outer=[(r + WALL, 0.0), (r + WALL, FLANGE_T)],
               inner=[(r, 0.0), (r, FLANGE_T)], fan=fan,
               info={"bore_d": fan.bore_d, "flange_t": FLANGE_T, "bolt_circle_d": fan.bolt_circle_d,
                     "hole_d": fan.hole_d, "holes": len(fan.hole_angles)})


def pvc_end(size: float, style: str) -> End:
    pipe_od = PIPE_OD_IN[size] * IN
    depth = SCH40_SOCKET_DEPTH_IN[size] * IN
    label = f"{size:g} in Sch 40 PVC {style}"
    if style == "spigot":
        od = pipe_od + SPIGOT_DIAMETRAL_ALLOWANCE
        ro, ri = od / 2, od / 2 - WALL
        length = depth + SPIGOT_EXTRA
        c = SPIGOT_CHAMFER
        return End(label, style, length, ri, outer=[(ro - c, 0.0), (ro, c), (ro, length)],
                   inner=[(ri, 0.0), (ri, length)],
                   info={"pipe_od": round(pipe_od, 2), "spigot_od": round(od, 2), "spigot_id": round(2 * ri, 2),
                         "spigot_length": round(length, 2), "fitting_socket_depth": round(depth, 2)})
    ri_sock = (pipe_od + SOCKET_DIAMETRAL_CLEARANCE) / 2
    ri_join = pipe_od / 2 - SOCKET_STOP
    ro = ri_sock + WALL
    length = depth + WALL  # socket plus the stop ledge
    return End(label, style, length, ri_join, outer=[(ro, 0.0), (ro, length)],
               inner=[(ri_sock, 0.0), (ri_sock, depth), (ri_join, depth), (ri_join, length)],
               info={"pipe_od": round(pipe_od, 2), "socket_id": round(2 * ri_sock, 2), "socket_depth": round(depth, 2),
                     "stop_ledge_id": round(2 * ri_join, 2)})


def bolt_keepout_r(fan: Fan) -> float:
    return fan.bolt_circle_d / 2 - BOLT_KEEPOUT_D / 2


def layout(a: End, b: End, taper_deg: float) -> dict:
    """Axial stack: end a (face on the bed), transition, end b (face on top). Returns z positions and profiles."""
    if b.kind == "fan":
        if a.kind == "fan":
            raise ValueError("Fan-to-fan adapters are not supported yet")
        a, b = b, a
    if not 0 < taper_deg <= 45:
        raise ValueError("taper half-angle must be in (0, 45] degrees so the cone prints without support")
    ra, rb = a.join_inner_r, b.join_inner_r
    taper_len = abs(rb - ra) / math.tan(math.radians(taper_deg))
    straight = 0.0
    if a.fan:
        # Keep bolt heads reachable: nothing wider than the keep-out radius in the first BOLT_ACCESS mm.
        if max(ra, rb) + WALL > bolt_keepout_r(a.fan):
            straight = BOLT_ACCESS          # straight neck first, then the flare
        else:
            taper_len = max(taper_len, BOLT_ACCESS)
    z_t0 = a.length
    z_t1 = z_t0 + straight + taper_len
    top = z_t1 + b.length

    def flip(pts):  # b's profile is measured from its face (at the top) downward
        return [(r, top - s) for r, s in reversed(pts)]

    outer = list(a.outer) + [(ra + WALL, z_t0 + straight)] + flip(b.outer)
    inner = list(a.inner) + [(ra, z_t0 + straight)] + flip(b.inner)
    return {"a": a, "b": b, "outer": outer, "inner": inner, "z_transition": (z_t0, z_t1), "top": top,
            "straight_neck": straight, "taper_len": taper_len}


def revolve(profile: list[tuple[float, float]]) -> trimesh.Trimesh:
    """Solid of revolution about Z of the region between the axis and the (r, z) polyline."""
    pts = [(0.0, profile[0][1])] + profile + [(0.0, profile[-1][1])]
    pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    poly = sg.Polygon(pts)
    if not poly.exterior.is_ccw:
        pts = pts[::-1]
    return trimesh.creation.revolve(np.array(pts + [pts[0]]), sections=SECTIONS)


def flange_plate(fan: Fan) -> trimesh.Trimesh:
    half = fan.frame / 2 - fan.corner_r
    square = sg.box(-half, -half, half, half).buffer(fan.corner_r, quad_segs=32)
    rb = fan.bolt_circle_d / 2
    holes = [sg.Point(rb * math.cos(math.radians(t)), rb * math.sin(math.radians(t))).buffer(fan.hole_d / 2, quad_segs=24)
             for t in fan.hole_angles]
    for h in holes:
        square = square.difference(h)
    return trimesh.creation.extrude_polygon(square, FLANGE_T)


def build(a_spec: str, b_spec: str, taper_deg: float = TAPER_HALF_ANGLE) -> tuple[trimesh.Trimesh, dict]:
    lay = layout(parse_fitting(a_spec), parse_fitting(b_spec), taper_deg)
    a = lay["a"]
    solid = revolve(lay["outer"])
    if a.fan:
        solid = trimesh.boolean.union([solid, flange_plate(a.fan)], engine="manifold")
    inner = list(lay["inner"])
    inner = [(inner[0][0], inner[0][1] - 1.0)] + inner + [(inner[-1][0], inner[-1][1] + 1.0)]
    mesh = trimesh.boolean.difference([solid, revolve(inner)], engine="manifold")
    return mesh, lay


def inner_r_at(lay: dict, z: float) -> float:
    pts = lay["inner"]
    rs = [r for (r0, z0), (r1, z1) in pairwise(pts) if min(z0, z1) <= z <= max(z0, z1)
          for r in ([min(r0, r1)] if z0 == z1 else [r0 + (r1 - r0) * (z - z0) / (z1 - z0)])]
    return min(rs)


def outer_r_max(lay: dict, z0: float, z1: float) -> float:
    pts = lay["outer"]
    rs = [r for (r, z) in pts if z0 <= z <= z1]
    rs += [float(np.interp(z, [p[1] for p in pts], [p[0] for p in pts])) for z in (z0, z1)]
    return float(max(rs))


def check(mesh: trimesh.Trimesh, lay: dict) -> dict:
    a, b = lay["a"], lay["b"]
    z_t0, z_t1 = lay["z_transition"]
    ext = [round(float(v), 2) for v in mesh.extents]
    rep = {
        "fittings": {"bottom (on bed)": {"name": a.label, **a.info}, "top": {"name": b.label, **b.info}},
        "overall_length_mm": round(lay["top"], 2), "overall_length_in": round(lay["top"] / IN, 2),
        "transition": {"from_id": round(2 * a.join_inner_r, 2), "to_id": round(2 * b.join_inner_r, 2),
                       "straight_neck": round(lay["straight_neck"], 2), "taper_length": round(lay["taper_len"], 2),
                       "z": [round(z_t0, 2), round(z_t1, 2)], "wall": WALL},
        "extents_mm": ext, "watertight": bool(mesh.is_watertight), "bodies": len(mesh.split(only_watertight=False)),
        "volume_cm3": round(float(mesh.volume) / 1000, 1), "warnings": [],
    }
    if a.fan:
        fan = a.fan
        keep = bolt_keepout_r(fan)
        worst = outer_r_max(lay, FLANGE_T, FLANGE_T + BOLT_ACCESS)
        rep["bolt_access"] = {"keepout_r": round(keep, 2), "max_outer_r_in_zone": round(worst, 2),
                              "zone_height": BOLT_ACCESS, "ok": worst <= keep + 1e-6}
        if b.kind == "spigot":
            # The PVC fitting slides down to the bottom of its socket; its mouth stops SPIGOT_EXTRA above the neck.
            mouth = lay["top"] - b.info["fitting_socket_depth"]
            rep["bolt_access"]["pvc_fitting_mouth_z"] = round(mouth, 2)
            rep["bolt_access"]["ok"] &= mouth >= FLANGE_T + BOLT_ACCESS - 1e-6
        hub_r = inner_r_at(lay, min(fan.hub_proud + 1.0, FLANGE_T))
        rep["hub_clearance"] = {"hub_d_assumed": fan.hub_d, "bore_d_at_face": round(2 * hub_r, 2),
                                "ok": hub_r >= fan.hub_d / 2 + HUB_CLEARANCE}
        for k in ("bolt_access", "hub_clearance"):
            if not rep[k]["ok"]:
                rep["warnings"].append(f"{k} check failed: {rep[k]}")
    rep["fits_bed"] = {name: bool(sorted(ext[:2]) <= sorted(vol[:2]) and ext[2] <= vol[2])
                       for name, vol in PRINTERS.items()}
    if not rep["watertight"] or rep["bodies"] != 1:
        rep["warnings"].append("Mesh is not a single closed body")
    return rep


def fit_test_rings(b: End) -> list[tuple[str, trimesh.Trimesh]]:
    """Short spigot rings at a few OD allowances, to press into a real fitting before printing the adapter."""
    if b.kind != "spigot":
        return []
    rings = []
    for allow in FIT_TEST_ALLOWANCES:
        od = b.info["pipe_od"] + allow
        ring = trimesh.boolean.difference([
            trimesh.creation.cylinder(radius=od / 2, height=FIT_TEST_RING_H, sections=SECTIONS),
            trimesh.creation.cylinder(radius=od / 2 - WALL, height=FIT_TEST_RING_H + 2, sections=SECTIONS),
        ], engine="manifold")
        ring.apply_translation([0, 0, FIT_TEST_RING_H / 2])
        rings.append((f"fit-ring-od{od:.2f}", ring))
    return rings


def render_section(mesh: trimesh.Trimesh, lay: dict, path: Path, title: str) -> Path:
    """Half-section through the axis with the key diameters, to check the profile at a glance."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sec = mesh.section(plane_origin=[0, 0, 0], plane_normal=[0, 1, 0])
    fig, ax = plt.subplots(figsize=(7, 8))
    for loop in sec.discrete:
        ax.fill(loop[:, 0], loop[:, 2], color="#4a7ab5", alpha=0.85, lw=0.6, ec="#1f3b5c")
    a, b = lay["a"], lay["b"]
    for z, d, txt in [(1.0, 2 * a.join_inner_r, f"ID {2 * a.join_inner_r:.1f}"),
                      (lay["top"] - 1.0, 2 * b.join_inner_r, f"ID {2 * b.join_inner_r:.1f}")]:
        ax.annotate("", (-d / 2, z), (d / 2, z), arrowprops={"arrowstyle": "<->", "color": "#c0392b"})
        ax.text(0, z + 2, txt, ha="center", color="#c0392b", fontsize=9)
    od = b.info.get("spigot_od") or b.info.get("socket_id")
    if od:
        title += f"\n{b.kind} {'OD' if b.kind == 'spigot' else 'ID'} {od:.2f} mm"
    ax.axhline(0, color="#c0392b", lw=1.5)
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    ax.set_title(f"{title}\nsection through the axis, mm (red line = build plate)", fontsize=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def slug(spec: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", spec.lower()).strip("-")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("a", help="first fitting, e.g. bfs-i06")
    ap.add_argument("b", help="second fitting, e.g. pvc-4-sch40-spigot")
    ap.add_argument("--taper-deg", type=float, default=TAPER_HALF_ANGLE, help="cone half-angle, degrees")
    ap.add_argument("--out", type=Path, help="output dir (default output/cad-adapter-<a>-to-<b>)")
    args = ap.parse_args(argv)
    mesh, lay = build(args.a, args.b, args.taper_deg)
    report = check(mesh, lay)
    stem = f"{slug(args.a)}-to-{slug(args.b)}"
    out = args.out or Path(f"output/cad-adapter-{stem}")
    out.mkdir(parents=True, exist_ok=True)
    files = printprep.export(mesh, out, stem, ["stl", "3mf"])
    title = f"{lay['a'].label} to {lay['b'].label}"
    files.append(printprep.render_preview(mesh, out / f"{stem}-preview.png"))
    files.append(render_section(mesh, lay, out / f"{stem}-section.png", title))
    for name, ring in fit_test_rings(lay["b"]):
        files += printprep.export(ring, out, name, ["stl"])
    report["files"] = [str(f) for f in files]
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
