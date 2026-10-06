"""Parametric duct adapter between two fittings, e.g. a fan flange to a PVC pipe spigot.

Coordinates: mm, Z = airflow axis. The first fitting sits on the bed at z = 0 (a fan flange prints face
down, no supports); the transition cone and the second fitting rise above it.

Fittings are given as text specs:
- Fans, by id in the fan library (cad/fanlib.py): "bfs-i06"
- PVC pipe, size + schedule + spigot/socket:  "pvc-4-sch40-spigot", "4in sch40 pvc socket", "1-1/2 sch 40 pvc spigot"
  spigot = the adapter end goes INTO a PVC fitting's socket (it replaces a piece of pipe).
  socket = the adapter end slips OVER a PVC pipe, which stops on an inner ledge.
- Tri-clamp (sanitary) ferrule by clamp size:  "triclamp-1.5", "1.5in tri-clamp"
- NPT pipe thread, size + male/female:         "npt-2-male", "2in fnpt", "2\" npt female"

Where the numbers come from:
- PVC pipe OD: standard NPS outside diameters (ASTM D1785), e.g. 4" = 4.500 in.
- PVC socket depth: ASTM D2466 Schedule 40 fittings as listed in Charlotte Pipe's Sch 40 submittal
  (4": entrance 4.518 in, bottom 4.491 in, +/-0.009, depth 2.000 in). Sch 80 fittings (D2467) are not
  in the table yet.
- NPT: ASME B1.20.1 (60 deg thread, taper 1:16 on diameter, thread height 0.8 x pitch, crest and root
  truncated 0.033 x pitch). E0 = D - (0.05 D + 1.1) p and L2 = (0.8 D + 6.8) p are the standard's formulas
  (they give the tabulated 2" values E0 2.26902 in, L2 0.7565 in); L1 (hand-tight engagement) is from the
  standard's table.
- Tri-clamp: flange OD, tube OD and tube ID from the common sizing chart (e.g. 1.5" clamp: 1.984 in flange on
  1.5 in tube); gasket bead diameters from gasket dimension charts (1.5": 1.718 in, which matches the groove
  on the user's working adapter exactly). The groove cross-section (3.8 mm wide, 1.6 mm deep), 20 deg clamp
  bevel and 2.84 mm rim are copied from the user's working 1.5" adapter and used for every size; they are
  not from a standard drawing, so print the fit-test piece first on a new size.
Change the constants below to correct any of them.

Run: python -m cad.adapter bfs-i06 pvc-4-sch40-spigot [--out DIR] [--taper-deg 15] [--fans LIBRARY.json]
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass, field, replace
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

import numpy as np
import shapely.geometry as sg
import trimesh

from cad import fanlib
from cad.fanlib import Fan
from meshy3d import printprep

IN = 25.4
GENERATOR_VERSION = "1.0"

# --- General adapter settings (defaults; the app can override the ones in Options) --------------
WALL = 3.5               # duct and pipe-end wall thickness
FLANGE_T = 10.0          # fan flange plate thickness (the user's tri-clamp adapter used ~9.5)
TAPER_HALF_ANGLE = 15.0  # cone half-angle in degrees; smaller = gentler (7 deg is a classic diffuser)
SECTIONS = 256           # facets around the circle
BOLT_ACCESS = 30.0       # clear height above the flange for bolt heads / nuts and a socket wrench
BOLT_KEEPOUT_FACTOR = 2.0  # keep-out circle around each bolt = this x hole diameter (24 mm for the 12 mm holes:
                           # an M10 hex head plus a socket wrench; 9 mm for M4 screws in 4.5 mm holes)
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
FIT_TEST_STEPS = (0.2, 0.0, -0.2)    # fit-test rings at the chosen allowance plus these

# Nominal size (inches) -> pipe OD (inches), ASTM D1785 / NPS. Also the D in the NPT formulas.
PIPE_OD_IN = {0.125: 0.405, 0.25: 0.540, 0.375: 0.675, 0.5: 0.840, 0.75: 1.050, 1.0: 1.315, 1.25: 1.660,
              1.5: 1.900, 2.0: 2.375, 2.5: 2.875, 3.0: 3.500, 4.0: 4.500, 6.0: 6.625, 8.0: 8.625,
              10.0: 10.750, 12.0: 12.750}
# Nominal size -> Schedule 40 socket depth (inches), ASTM D2466 per Charlotte Pipe's submittal.
SCH40_SOCKET_DEPTH_IN = {0.5: 0.688, 0.75: 0.719, 1.0: 0.875, 1.25: 0.938, 1.5: 1.094, 2.0: 1.156, 2.5: 1.750,
                         3.0: 1.875, 4.0: 2.000, 6.0: 3.000, 8.0: 4.000, 10.0: 5.000, 12.0: 6.000}

# Tri-clamp: clamp size -> flange OD, tube OD, tube ID, gasket bead diameter (inches).
TRICLAMP = {
    1.5: (1.984, 1.5, 1.37, 1.718),
    2.0: (2.516, 2.0, 1.87, 2.218),
    2.5: (3.047, 2.5, 2.37, 2.781),
    3.0: (3.579, 3.0, 2.87, 3.281),
    4.0: (4.682, 4.0, 3.83, 4.345),
    6.0: (6.570, 6.0, 5.78, 6.176),
}
TRICLAMP_PROFILE = {"rim_t": 2.84, "bevel_deg": 20.0, "groove_w": 3.8, "groove_depth": 1.59}  # mm, deg
TRICLAMP_MIN_WALL = 2.0    # bore = tube ID, made smaller if needed to keep this much wall under the bevel
TRICLAMP_NECK = 10.0       # plain tube length behind the bevel, room for the clamp jaws

# NPT, ASME B1.20.1: nominal size -> (threads per inch, L1 hand-tight engagement in inches).
NPT = {0.125: (27, 0.1615), 0.25: (18, 0.2278), 0.375: (18, 0.240), 0.5: (14, 0.320), 0.75: (14, 0.339),
       1.0: (11.5, 0.400), 1.25: (11.5, 0.420), 1.5: (11.5, 0.420), 2.0: (11.5, 0.436), 2.5: (8, 0.682),
       3.0: (8, 0.766), 4.0: (8, 0.844)}
NPT_FINE_TPI = 18            # at or above this, warn: threads this fine print poorly with a 0.4 mm nozzle
NPT_RADIAL_CLEARANCE = 0.1   # printed threads come out fat: male made this much smaller, female larger
NPT_EXTRA_THREADS = 2        # thread length = L2 + this many pitches (male) / tapped depth (female)
NPT_MALE_WALL = 3.0          # wall under the male thread roots (less on small sizes, see npt_end)
NPT_FEMALE_WALL = 5.0        # wall outside the female thread majors
NPT_COLLAR = 6.0             # plain section between the thread and the transition
THREAD_SAMPLES_PER_PITCH = 24
THREAD_SECTIONS = 360

# Build volumes (X, Y, Z) of the user's printers, mm.
PRINTERS = {"Bambu Lab P1S": (256, 256, 256), "Bambu Lab H2D": (350, 320, 325)}


@dataclass(frozen=True)
class Options:
    taper_deg: float = TAPER_HALF_ANGLE
    wall: float = WALL
    spigot_allowance: float = SPIGOT_DIAMETRAL_ALLOWANCE
    socket_clearance: float = SOCKET_DIAMETRAL_CLEARANCE
    npt_clearance: float = NPT_RADIAL_CLEARANCE

    def check(self) -> None:
        if not 0 < self.taper_deg <= 45:
            raise ValueError("Taper half-angle must be between 0 and 45 degrees so the cone prints without support")
        if not 1.2 <= self.wall <= 10:
            raise ValueError("Wall must be between 1.2 and 10 mm")
        if not -2 <= self.spigot_allowance <= 1:
            raise ValueError("Spigot allowance must be between -2 and +1 mm")
        if not 0 <= self.socket_clearance <= 3:
            raise ValueError("Socket clearance must be between 0 and 3 mm")
        if not 0 <= self.npt_clearance <= 0.5:
            raise ValueError("NPT clearance must be between 0 and 0.5 mm")


DEFAULT = Options()


@dataclass
class End:
    """One fitting. Profiles are (r, z) points measured from this end's face (s = 0) toward the transition."""
    label: str
    kind: str                      # "fan" | "spigot" | "socket" | "triclamp" | "npt-male" | "npt-female"
    length: float                  # along the axis
    join_inner_r: float            # duct inner radius where the transition attaches
    outer: list[tuple[float, float]]
    inner: list[tuple[float, float]]
    info: dict = field(default_factory=dict)
    fan: Fan | None = None
    add: list[trimesh.Trimesh] = field(default_factory=list)   # extra solids (thread), same local frame: z = s
    cut: list[trimesh.Trimesh] = field(default_factory=list)   # solids to remove (female thread, groove)
    warnings: list[str] = field(default_factory=list)

    @property
    def join_outer_r(self) -> float:
        return self.outer[-1][0]


def size_label(size: float) -> str:
    """0.125 -> '1/8', 1.5 -> '1-1/2', 4.0 -> '4'."""
    frac = Fraction(size).limit_denominator(16)
    whole, rest = divmod(frac, 1)
    if not rest:
        return str(whole)
    return f"{rest}" if not whole else f"{whole}-{rest}"


def catalog() -> dict:
    """Fitting types and sizes the generator knows, for the app's dropdowns. 'spec' is what parse_fitting takes."""
    def entries(sizes, fmt):
        return [{"size": size_label(s), "spec": fmt.format(size_label(s))} for s in sorted(sizes)]
    return {
        "pvc-spigot": {"label": "PVC Sch 40 spigot (goes into a PVC fitting)",
                       "sizes": entries(SCH40_SOCKET_DEPTH_IN, "pvc-{}-sch40-spigot")},
        "pvc-socket": {"label": "PVC Sch 40 socket (slips over a PVC pipe)",
                       "sizes": entries(SCH40_SOCKET_DEPTH_IN, "pvc-{}-sch40-socket")},
        "npt-male": {"label": "NPT male (threads on the outside)", "sizes": entries(NPT, "npt-{}-male")},
        "npt-female": {"label": "NPT female (threads on the inside)", "sizes": entries(NPT, "npt-{}-female")},
        "triclamp": {"label": "Tri-clamp ferrule", "sizes": entries(TRICLAMP, "triclamp-{}")},
    }


def parse_size(text: str) -> float:
    """'4', '1-1/2', '1 1/2', '1.5', '3/4' -> inches."""
    text = text.strip().replace(" ", "-")
    if "-" in text and "/" in text:
        whole, frac = text.split("-", 1)
        return float(int(whole) + Fraction(frac))
    return float(Fraction(text))


def size_from(spec: str, s: str, words: str) -> float:
    rest = re.sub(words + r"|inches|inch|in\b", " ", s)
    size_txt = " ".join(t for t in re.split(r"[\s-]+", rest) if t)
    try:
        return parse_size(size_txt)
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"{spec!r}: could not read a size from {size_txt!r}") from None


def _known(sizes) -> str:
    return ", ".join(size_label(s) for s in sorted(sizes))


def parse_fitting(spec: str, fans: dict[str, Fan] | None = None, opt: Options = DEFAULT) -> End:
    fans = fanlib.load() if fans is None else fans
    s = spec.lower().strip().replace('"', "in ")
    key = s.removeprefix("fan-").removeprefix("fan ")
    if key in fans:
        return fan_end(fans[key], opt)
    if "pvc" in s:
        style = re.search(r"\b(spigot|socket)\b", s.replace("-", " "))
        sched = re.search(r"sch(?:edule)?[\s-]*(\d+)", s)
        if not style or not sched:
            raise ValueError(f"{spec!r}: PVC spec needs a schedule and spigot/socket, e.g. 'pvc-4-sch40-spigot'")
        rest = s[:sched.start()] + " " + s[sched.end():]
        size = size_from(spec, rest, r"pvc|spigot|socket")
        if size not in SCH40_SOCKET_DEPTH_IN:
            raise ValueError(f"{spec!r}: no PVC data for {size:g} in; known sizes: {_known(SCH40_SOCKET_DEPTH_IN)}")
        if sched.group(1) != "40":
            raise ValueError(f"{spec!r}: only Schedule 40 socket depths are in the table so far")
        return pvc_end(size, style.group(1), opt)
    if re.search(r"tri[\s-]*clamp|sanitary|\btc\b", s):
        size = size_from(spec, s, r"tri[\s-]*clamp|sanitary|\btc\b|ferrule")
        if size not in TRICLAMP:
            raise ValueError(f"{spec!r}: no tri-clamp data for {size:g} in; known sizes: {_known(TRICLAMP)}")
        return triclamp_end(size, opt)
    if re.search(r"npt", s):
        gender = re.search(r"\b(male|female|m(?=npt)|f(?=npt))", s)
        if not gender:
            raise ValueError(f"{spec!r}: say male or female, e.g. 'npt-2-male' (male = threads on the outside)")
        size = size_from(spec, s, r"[mf]?npt|female|male")
        if size not in NPT:
            raise ValueError(f"{spec!r}: no NPT data for {size:g} in; known sizes: {_known(NPT)}")
        return npt_end(size, gender.group(1).startswith("m"), opt)
    raise ValueError(f"Unknown fitting {spec!r}. Fans: {', '.join(sorted(fans))}; PVC like 'pvc-4-sch40-spigot'; "
                     "'triclamp-1.5'; 'npt-2-male'.")


def fan_end(fan: Fan, opt: Options = DEFAULT) -> End:
    r = fan.bore_d / 2
    warnings = [] if fan.verified else [f"Fan '{fan.name}' is not marked verified; check its dimensions."]
    return End(fan.name, "fan", FLANGE_T, r, outer=[(r + opt.wall, 0.0), (r + opt.wall, FLANGE_T)],
               inner=[(r, 0.0), (r, FLANGE_T)], fan=fan, warnings=warnings,
               info={"fan_id": fan.id, "bore_d": fan.bore_d, "flange_t": FLANGE_T, "frame": fan.frame,
                     "bolt_circle_d": round(fan.bolt_circle_d, 2), "hole_d": fan.hole_d, "holes": 4})


def pvc_end(size: float, style: str, opt: Options = DEFAULT) -> End:
    pipe_od = PIPE_OD_IN[size] * IN
    depth = SCH40_SOCKET_DEPTH_IN[size] * IN
    label = f"{size_label(size)} in Sch 40 PVC {style}"
    if style == "spigot":
        od = pipe_od + opt.spigot_allowance
        ro, ri = od / 2, od / 2 - opt.wall
        length = depth + SPIGOT_EXTRA
        c = SPIGOT_CHAMFER
        return End(label, style, length, ri, outer=[(ro - c, 0.0), (ro, c), (ro, length)],
                   inner=[(ri, 0.0), (ri, length)],
                   info={"pipe_od": round(pipe_od, 2), "spigot_od": round(od, 2), "spigot_id": round(2 * ri, 2),
                         "spigot_length": round(length, 2), "fitting_socket_depth": round(depth, 2)})
    ri_sock = (pipe_od + opt.socket_clearance) / 2
    ri_join = pipe_od / 2 - SOCKET_STOP
    ro = ri_sock + opt.wall
    length = depth + opt.wall  # socket plus the stop ledge
    return End(label, style, length, ri_join, outer=[(ro, 0.0), (ro, length)],
               inner=[(ri_sock, 0.0), (ri_sock, depth), (ri_join, depth), (ri_join, length)],
               info={"pipe_od": round(pipe_od, 2), "socket_id": round(2 * ri_sock, 2), "socket_depth": round(depth, 2),
                     "stop_ledge_id": round(2 * ri_join, 2)})


def triclamp_end(size: float, opt: Options = DEFAULT) -> End:
    flange_in, tube_od_in, tube_id_in, bead_in = TRICLAMP[size]
    p = TRICLAMP_PROFILE
    rf, rt = flange_in * IN / 2, tube_od_in * IN / 2
    ri = min(tube_id_in * IN / 2, rt - TRICLAMP_MIN_WALL)
    s_bevel = p["rim_t"] + (rf - rt) * math.tan(math.radians(p["bevel_deg"]))
    length = s_bevel + TRICLAMP_NECK
    # Gasket groove: circular segment of the given width and depth, cut into the face (s = 0) on the bead circle.
    w, dep = p["groove_w"], p["groove_depth"]
    rg = (w * w / 4 + dep * dep) / (2 * dep)
    center_s = dep - rg
    ang = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    rc = bead_in * IN / 2
    circle = np.c_[rc + rg * np.cos(ang), center_s + rg * np.sin(ang)]
    groove = trimesh.creation.revolve(np.vstack([circle, circle[:1]]), sections=SECTIONS)
    return End(f"{size_label(size)} in tri-clamp ferrule", "triclamp", length, ri,
               outer=[(rf, 0.0), (rf, p["rim_t"]), (rt, s_bevel), (rt, length)],
               inner=[(ri, 0.0), (ri, length)], cut=[groove],
               info={"flange_od": round(2 * rf, 2), "tube_od": round(2 * rt, 2), "bore": round(2 * ri, 2),
                     "gasket_bead_d": round(2 * rc, 2), "groove_w": w, "groove_depth": dep,
                     "bevel_deg": p["bevel_deg"]})


def thread_radius(theta: np.ndarray, s: np.ndarray, pitch: float, r_pitch: np.ndarray) -> np.ndarray:
    """Radius of a right-hand 60 deg thread surface, truncated to 0.8 x pitch, about the pitch radius."""
    big_h = pitch * math.sqrt(3) / 2
    trunc = (big_h - 0.8 * pitch) / 2
    phase = np.mod(s / pitch - theta / (2 * np.pi), 1.0)
    sharp = r_pitch - big_h / 2 + big_h * (1 - 2 * np.abs(phase - 0.5))
    return np.clip(sharp, r_pitch - big_h / 2 + trunc, r_pitch + big_h / 2 - trunc)


def threaded_tube(s0: float, s1: float, pitch: float, r_in, r_out) -> trimesh.Trimesh:
    """Closed tube between radius functions r_in(theta, s) and r_out(theta, s) (arrays), z = s."""
    n_t = THREAD_SECTIONS
    n_s = max(2, math.ceil((s1 - s0) / pitch * THREAD_SAMPLES_PER_PITCH) + 1)
    theta, s = np.meshgrid(np.linspace(0, 2 * np.pi, n_t, endpoint=False), np.linspace(s0, s1, n_s), indexing="ij")
    verts = []
    for r in (r_out(theta, s), r_in(theta, s)):
        verts.append(np.stack([r * np.cos(theta), r * np.sin(theta), s], axis=-1).reshape(-1, 3))
    verts = np.vstack(verts)
    idx = np.arange(n_t * n_s).reshape(n_t, n_s)
    inner_off = n_t * n_s
    i, j = np.meshgrid(np.arange(n_t), np.arange(n_s - 1), indexing="ij")
    a, b = idx[i, j], idx[(i + 1) % n_t, j]
    c, d = idx[(i + 1) % n_t, j + 1], idx[i, j + 1]
    quads = [np.stack([a, b, c, d], -1).reshape(-1, 4), np.stack([a, d, c, b], -1).reshape(-1, 4) + inner_off]
    k = np.arange(n_t)
    for col, flip in ((0, True), (n_s - 1, False)):
        o0, o1 = idx[k, col], idx[(k + 1) % n_t, col]
        q = np.stack([o0, o1, o1 + inner_off, o0 + inner_off], -1)
        quads.append(q[:, ::-1] if flip else q)
    quads = np.vstack(quads)
    faces = np.vstack([quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]])
    mesh = trimesh.Trimesh(verts, faces, process=True)
    mesh.fix_normals()
    return mesh


def npt_dims(size: float) -> dict:
    """ASME B1.20.1 basic dimensions in inches: D, pitch, E0, E1, L1, L2."""
    tpi, l1 = NPT[size]
    d, p = PIPE_OD_IN[size], 1 / tpi
    e0 = d - (0.05 * d + 1.1) * p
    return {"tpi": tpi, "D": d, "p": p, "E0": e0, "E1": e0 + l1 / 16, "L1": l1, "L2": (0.8 * d + 6.8) * p}


def npt_end(size: float, male: bool, opt: Options = DEFAULT) -> End:
    d = npt_dims(size)
    p = d["p"] * IN
    big_h = p * math.sqrt(3) / 2
    trunc = (big_h - 0.8 * p) / 2
    t_len = d["L2"] * IN + NPT_EXTRA_THREADS * p
    length = t_len + NPT_COLLAR
    c = opt.npt_clearance
    label = f"{size_label(size)} in NPT {'male' if male else 'female'}"
    warnings = []
    if d["tpi"] >= NPT_FINE_TPI:
        warnings.append(f"{label}: {d['tpi']} threads per inch ({p:.2f} mm pitch) is fine for FDM; expect a "
                        "rough thread and use sealant. A 0.2 mm nozzle helps.")
    if male:
        # s = 0 is the small end of the taper (the tip).
        def r_pitch(s):
            return (d["E0"] * IN + s / 16) / 2 - c

        def root(s):
            return r_pitch(s) - big_h / 2 + trunc

        def major(s):
            return r_pitch(s) + big_h / 2 - trunc

        wall = min(NPT_MALE_WALL, max(1.2, 0.3 * root(0)))
        ri = root(0) - wall
        thread = threaded_tube(0.0, t_len + 0.5, p, lambda t, s: np.full_like(s, ri - 0.5),
                               lambda t, s: np.minimum(thread_radius(t, s, p, r_pitch(s)), root(0) + 0.5 + s))
        return End(label, "npt-male", length, ri,
                   outer=[(root(0) - 0.3, 0.0), (root(t_len) - 0.3, t_len), (major(t_len), t_len),
                          (major(t_len), length)],
                   inner=[(ri, 0.0), (ri, length)], add=[thread], warnings=warnings,
                   info={"tpi": d["tpi"], "major_d_at_tip": round(2 * major(0), 2),
                         "major_d_at_thread_end": round(2 * major(t_len), 2), "thread_length": round(t_len, 2),
                         "bore": round(2 * ri, 2), "radial_clearance": c})

    # Female: s = 0 is the mouth, where the pitch diameter is E1 (hand-tight plane at the fitting face).
    def r_pitch(s):
        return (d["E1"] * IN - s / 16) / 2 + c

    def minor(s):
        return r_pitch(s) - big_h / 2 + trunc

    def major(s):
        return r_pitch(s) + big_h / 2 - trunc

    ro = major(0) + max(opt.wall, NPT_FEMALE_WALL)
    ri = minor(t_len) - 0.5
    core = threaded_tube(-1.0, t_len, p, lambda t, s: np.full_like(s, ri - 1.0),
                         lambda t, s: np.maximum(thread_radius(t, s, p, r_pitch(s)), major(0) + 0.5 - s))
    return End(label, "npt-female", length, ri, outer=[(ro, 0.0), (ro, length)],
               inner=[(ri, 0.0), (ri, length)], cut=[core], warnings=warnings,
               info={"tpi": d["tpi"], "major_d_at_mouth": round(2 * major(0), 2), "tapped_depth": round(t_len, 2),
                     "outer_d": round(2 * ro, 2), "bore_below_thread": round(2 * ri, 2), "radial_clearance": c})


def bolt_keepout_r(fan: Fan) -> float:
    return fan.bolt_circle_d / 2 - BOLT_KEEPOUT_FACTOR * fan.hole_d / 2


def layout(a: End, b: End, opt: Options = DEFAULT) -> dict:
    """Axial stack: end a (face on the bed), transition, end b (face on top). Returns z positions and profiles."""
    if b.kind == "fan":
        if a.kind == "fan":
            raise ValueError("Fan-to-fan adapters are not supported yet")
        a, b = b, a
    opt.check()
    ra, rb = a.join_inner_r, b.join_inner_r
    oa, ob = a.join_outer_r, b.join_outer_r
    taper_len = max(abs(rb - ra), abs(ob - oa)) / math.tan(math.radians(opt.taper_deg))
    straight = 0.0
    if a.fan:
        # Keep bolt heads reachable: nothing wider than the keep-out radius in the first BOLT_ACCESS mm.
        if max(oa, ob) > bolt_keepout_r(a.fan):
            straight = BOLT_ACCESS          # straight neck first, then the flare
        else:
            taper_len = max(taper_len, BOLT_ACCESS)
    z_t0 = a.length
    z_t1 = z_t0 + straight + taper_len
    top = z_t1 + b.length

    def flip(pts):  # b's profile is measured from its face (at the top) downward
        return [(r, top - s) for r, s in reversed(pts)]

    outer = list(a.outer) + [(oa, z_t0 + straight)] + flip(b.outer)
    inner = list(a.inner) + [(ra, z_t0 + straight)] + flip(b.inner)
    return {"a": a, "b": b, "outer": outer, "inner": inner, "z_transition": (z_t0, z_t1), "top": top,
            "straight_neck": straight, "taper_len": taper_len, "b_transform": face_up(top), "options": opt}


def face_up(top: float) -> np.ndarray:
    """Local end frame (face at z = 0, body toward +z) -> face at z = top, body below. A rotation, so
    thread handedness is kept."""
    m = trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0])
    m[2, 3] = top
    return m


def placed(meshes: list[trimesh.Trimesh], transform: np.ndarray | None) -> list[trimesh.Trimesh]:
    out = [m.copy() for m in meshes]
    if transform is not None:
        for m in out:
            m.apply_transform(transform)
    return out


def solid_from(outer, inner, adds, cuts, plate=None) -> trimesh.Trimesh:
    solid = trimesh.boolean.union([revolve(outer), *adds, *([plate] if plate is not None else [])], engine="manifold")
    inner = [(inner[0][0], inner[0][1] - 1.0)] + list(inner) + [(inner[-1][0], inner[-1][1] + 1.0)]
    return trimesh.boolean.difference([solid, revolve(inner), *cuts], engine="manifold")


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
    square = sg.box(-half, -half, half, half)
    if fan.corner_r > 0:
        square = square.buffer(fan.corner_r, quad_segs=32)
    rb = fan.bolt_circle_d / 2
    for t in fan.hole_angles:
        hole = sg.Point(rb * math.cos(math.radians(t)), rb * math.sin(math.radians(t))).buffer(fan.hole_d / 2,
                                                                                              quad_segs=24)
        square = square.difference(hole)
    return trimesh.creation.extrude_polygon(square, FLANGE_T)


def build(a_spec: str, b_spec: str, opt: Options | float = DEFAULT,
          fans: dict[str, Fan] | None = None) -> tuple[trimesh.Trimesh, dict]:
    if not isinstance(opt, Options):  # older call style: build(a, b, taper_deg)
        opt = replace(DEFAULT, taper_deg=float(opt))
    opt.check()
    fans = fanlib.load() if fans is None else fans
    lay = layout(parse_fitting(a_spec, fans, opt), parse_fitting(b_spec, fans, opt), opt)
    a, b, tb = lay["a"], lay["b"], lay["b_transform"]
    mesh = solid_from(lay["outer"], lay["inner"], placed(a.add, None) + placed(b.add, tb),
                      placed(a.cut, None) + placed(b.cut, tb), flange_plate(a.fan) if a.fan else None)
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
    opt = lay.get("options", DEFAULT)
    z_t0, z_t1 = lay["z_transition"]
    ext = [round(float(v), 2) for v in mesh.extents]
    rep = {
        "generator_version": GENERATOR_VERSION,
        "options": {k: getattr(opt, k) for k in opt.__dataclass_fields__},
        "fittings": {"bottom (on bed)": {"name": a.label, **a.info}, "top": {"name": b.label, **b.info}},
        "overall_length_mm": round(lay["top"], 2), "overall_length_in": round(lay["top"] / IN, 2),
        "transition": {"from_id": round(2 * a.join_inner_r, 2), "to_id": round(2 * b.join_inner_r, 2),
                       "straight_neck": round(lay["straight_neck"], 2), "taper_length": round(lay["taper_len"], 2),
                       "z": [round(z_t0, 2), round(z_t1, 2)],
                       "wall_at_ends": [round(a.join_outer_r - a.join_inner_r, 2),
                                        round(b.join_outer_r - b.join_inner_r, 2)]},
        "extents_mm": ext, "watertight": bool(mesh.is_watertight), "bodies": len(mesh.split(only_watertight=False)),
        "volume_cm3": round(float(mesh.volume) / 1000, 1), "warnings": [*a.warnings, *b.warnings],
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
        if not rep["bolt_access"]["ok"]:
            rep["warnings"].append(
                f"Bolt heads may be hard to reach: the adapter reaches {worst:.1f} mm from the center within "
                f"{BOLT_ACCESS:g} mm of the flange, but the bolt heads need it inside {keep:.1f} mm.")
        if a.join_outer_r > fan.frame / 2:
            rep["warnings"].append(
                f"The duct wall (Ø{2 * a.join_outer_r:.1f}) is wider than the {fan.frame:g} mm frame, so it overhangs the "
                "frame's flat sides slightly. It prints fine; check nothing next to the fan is in the way.")
        if not rep["hub_clearance"]["ok"]:
            rep["warnings"].append(
                f"The fan's hub plate (Ø{fan.hub_d:g}) may touch the adapter: the bore at the flange is "
                f"Ø{2 * hub_r:.1f}, which leaves less than {HUB_CLEARANCE:g} mm around it.")
    rep["fits_bed"] = {name: bool(sorted(ext[:2]) <= sorted(vol[:2]) and ext[2] <= vol[2])
                       for name, vol in PRINTERS.items()}
    if not any(rep["fits_bed"].values()):
        rep["warnings"].append("Too big for both printers' build volumes.")
    if not rep["watertight"] or rep["bodies"] != 1:
        rep["warnings"].append("Mesh is not a single closed body")
    return rep


def fit_test_pieces(b: End, opt: Options = DEFAULT) -> list[tuple[str, trimesh.Trimesh]]:
    """Cheap prints to try against the real fitting before printing the adapter: spigot rings at a few OD
    allowances, or the thread / ferrule end on its own (face up, as on the adapter)."""
    if b.kind in ("npt-male", "npt-female", "triclamp"):
        tf = face_up(b.length)
        return [(f"fit-test-{slug(b.label)}", solid_from([(r, b.length - s) for r, s in reversed(b.outer)],
                                                         [(r, b.length - s) for r, s in reversed(b.inner)],
                                                         placed(b.add, tf), placed(b.cut, tf)))]
    if b.kind != "spigot":
        return []
    rings = []
    for step in FIT_TEST_STEPS:
        od = b.info["pipe_od"] + opt.spigot_allowance + step
        ring = trimesh.boolean.difference([
            trimesh.creation.cylinder(radius=od / 2, height=FIT_TEST_RING_H, sections=SECTIONS),
            trimesh.creation.cylinder(radius=od / 2 - opt.wall, height=FIT_TEST_RING_H + 2, sections=SECTIONS),
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
    key = {"spigot": "spigot_od", "socket": "socket_id", "triclamp": "flange_od", "npt-male": "major_d_at_tip",
           "npt-female": "major_d_at_mouth"}.get(b.kind)
    if key:
        title += f"\n{key.replace('_', ' ')} {b.info[key]:.2f} mm"
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


def generate(a_spec: str, b_spec: str, out: Path, opt: Options = DEFAULT,
             fans: dict[str, Fan] | None = None) -> dict:
    """Build, check and write everything for one adapter into out/. Returns the report (also report.json)."""
    mesh, lay = build(a_spec, b_spec, opt, fans)
    report = check(mesh, lay)
    stem = f"{slug(lay['a'].label)}-to-{slug(lay['b'].label)}"
    out.mkdir(parents=True, exist_ok=True)
    files = printprep.export(mesh, out, stem, ["stl", "3mf"])
    title = f"{lay['a'].label} to {lay['b'].label}"
    files.append(printprep.render_preview(mesh, out / f"{stem}-preview.png"))
    files.append(render_section(mesh, lay, out / f"{stem}-section.png", title))
    for name, piece in fit_test_pieces(lay["b"], opt):
        files += printprep.export(piece, out, name, ["stl"])
    report["title"] = title
    report["stem"] = stem
    report["files"] = [f.name for f in files]
    (out / "report.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("a", help="first fitting, e.g. bfs-i06")
    ap.add_argument("b", help="second fitting, e.g. pvc-4-sch40-spigot")
    ap.add_argument("--taper-deg", type=float, default=TAPER_HALF_ANGLE, help="cone half-angle, degrees")
    ap.add_argument("--fans", type=Path, help="user fan library JSON (in addition to the built-in fans)")
    ap.add_argument("--out", type=Path, help="output dir (default output/cad-adapter-<a>-to-<b>)")
    args = ap.parse_args(argv)
    opt = replace(DEFAULT, taper_deg=args.taper_deg)
    out = args.out or Path(f"output/cad-adapter-{slug(args.a)}-to-{slug(args.b)}")
    report = generate(args.a, args.b, out, opt, fanlib.load(args.fans))
    report["files"] = [str(out / f) for f in report["files"]]
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
