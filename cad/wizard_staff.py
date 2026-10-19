"""5 ft gnarled-wood wizard's staff, printed in segments, with a hidden 1/2" PVC core.

Layout (mm, Z up, staff axis on Z, foot at z=0):
- Shaft: a twisting, knotted "wood" surface around a straight 22.6 mm bore for 1/2" Schedule 40 PVC
  (OD 0.840 in = 21.34 mm; ~0.6 mm clearance per side since printed holes come out a bit small and
  the pipe has to pass through several segments).
- Joints: each segment ends in a 20 mm tube spigot with a key rib; the next segment's bottom has a
  matching keyed socket, so segments only go together one way and the bark pattern lines up. The PVC
  through the middle carries the bending load; the spigots only locate and add shear strength.
- Foot: the bottom segment's bore is closed at the bottom, so the pipe is hidden.
- Head: separate piece with a cup that the bubble maker slides into, ringed by branches. The cup is
  sized by WAND_* below. Placeholder values: the user's wand hasn't been measured yet.

Every segment prints upright (spigot up) on the H2D without supports; the head's branches lean at
most ~30 degrees from vertical.

Run: python -m cad.wizard_staff [--out DIR]
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import manifold3d as m3
import numpy as np
import trimesh

from meshy3d import printprep

# --- Overall --------------------------------------------------------------------------------------
TOTAL_H = 1524.0                    # 5 ft, foot to branch tips
SHAFT_SEGMENTS = 5                  # shaft pieces below the head
HEAD_H = 230.0                      # head piece: joint, flare, cup and branches
MAX_PRINT_H = 300.0                 # stay under the H2D's height with margin

# --- Shaft surface --------------------------------------------------------------------------------
R0 = 22.0                           # mean shaft radius (44 mm thick)
R_MIN = 19.5                        # never thinner than this (wall around the bore >= ~8 mm)
TWIST = 2 * np.pi / 450.0           # bark ridges make a full turn every 450 mm
FOOT_FLARE, FOOT_FLARE_H = 5.0, 45.0
KNOTS = 30                          # bumps scattered along the shaft
SEED = 7

# --- PVC and joints -------------------------------------------------------------------------------
PVC_OD = 21.34                      # 1/2" Schedule 40 (0.840 in)
BORE_D = 22.6
FOOT_T = 8.0                        # closed bottom under the pipe
SPIGOT_OD, SPIGOT_L = 28.0, 20.0
JOINT_CLEAR = 0.25                  # per side, spigot in socket
KEY_W, KEY_H = 4.0, 1.6             # key rib on the spigot (width, radial height)
PIPE_INTO_HEAD = 40.0               # pipe continues this far past the last shaft segment

# --- Head / bubble wand cup (PLACEHOLDERS until the wand is measured) -----------------------------
WAND_D = 45.0                       # inside diameter of the cup the bubble maker slides into
WAND_DEPTH = 60.0                   # how deep it goes in
WAND_CLEAR = 0.4                    # per side
CUP_WALL = 5.0
BRANCHES = 5
BRANCH_R0, BRANCH_R1 = 6.0, 2.5     # branch radius at the base and the tip

N_THETA = 160
DZ = 1.5


def _noise_params():
    rng = np.random.default_rng(SEED)
    waves = [(k, rng.uniform(0.6, 1.4) * a, rng.uniform(0, 2 * np.pi), rng.uniform(150, 400))
             for k, a in ((2, 1.8), (3, 1.4), (5, 0.9), (7, 0.7), (11, 0.55), (13, 0.45), (17, 0.35))]
    knots = [(rng.uniform(0, 2 * np.pi), rng.uniform(60, TOTAL_H - HEAD_H + 60), rng.uniform(3.0, 5.0))
             for _ in range(KNOTS)]
    return waves, knots


WAVES, KNOT_LIST = _noise_params()


def radius(theta: np.ndarray, z: np.ndarray, base: np.ndarray | float = R0) -> np.ndarray:
    """Outer radius of the shaft at angle theta, height z: twisting bark ridges, slow wobble, knots."""
    r = base + FOOT_FLARE * np.exp(-z / FOOT_FLARE_H)
    for k, a, phase, wl in WAVES:
        # each ridge family twists along the staff and drifts in phase with height
        r = r + a * np.cos(k * (theta - TWIST * z) + phase + 1.5 * np.sin(2 * np.pi * z / wl))
    for t0, z0, amp in KNOT_LIST:
        d = np.angle(np.exp(1j * (theta - t0)))
        r = r + amp * np.exp(-(d / 0.4) ** 2 - ((z - z0) / 16.0) ** 2)
    return np.maximum(r, R_MIN)


def loft(z0: float, z1: float, r_fn) -> trimesh.Trimesh:
    """Closed solid between z0 and z1 whose outline at each height is r_fn(theta, z) (star-shaped)."""
    n = max(2, int(np.ceil((z1 - z0) / DZ)) + 1)
    zs = np.linspace(z0, z1, n)
    th = np.linspace(0, 2 * np.pi, N_THETA, endpoint=False)
    T, Z = np.meshgrid(th, zs)
    R = r_fn(T, Z)
    verts = np.stack([R * np.cos(T), R * np.sin(T), Z], axis=-1).reshape(-1, 3)
    faces = []
    idx = np.arange(n * N_THETA).reshape(n, N_THETA)
    a, b = idx[:-1], np.roll(idx[:-1], -1, axis=1)
    c, d = idx[1:], np.roll(idx[1:], -1, axis=1)
    faces += [np.stack([a, b, d], -1).reshape(-1, 3), np.stack([a, d, c], -1).reshape(-1, 3)]
    bot, top = len(verts), len(verts) + 1
    verts = np.vstack([verts, [0, 0, z0], [0, 0, z1]])
    faces.append(np.stack([np.full(N_THETA, bot), np.roll(idx[0], -1), idx[0]], -1))
    faces.append(np.stack([np.full(N_THETA, top), idx[-1], np.roll(idx[-1], -1)], -1))
    return trimesh.Trimesh(verts, np.vstack(faces), process=True)


def to_m(mesh: trimesh.Trimesh) -> m3.Manifold:
    return m3.Manifold(m3.Mesh(np.asarray(mesh.vertices, np.float32), np.asarray(mesh.faces, np.uint32)))


def to_t(man: m3.Manifold) -> trimesh.Trimesh:
    mesh = man.to_mesh()
    return trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=False)


def cyl(r: float, z0: float, z1: float, r1: float | None = None) -> m3.Manifold:
    return m3.Manifold.cylinder(z1 - z0, r, r if r1 is None else r1, 96).translate((0, 0, z0))


def key(r_in: float, r_out: float, w: float, z0: float, z1: float) -> m3.Manifold:
    """Radial rib at angle 0 (along +X)."""
    return m3.Manifold.cube((r_out - r_in, w, z1 - z0)).translate((r_in, -w / 2, z0))


def spigot(z: float) -> m3.Manifold:
    """Keyed tube on top of a segment at height z; 1 mm chamfer at the tip for easy entry."""
    r = SPIGOT_OD / 2
    body = cyl(r, z - 0.5, z + SPIGOT_L - 1) + cyl(r, z + SPIGOT_L - 1, z + SPIGOT_L, r - 1)
    rib = key(r - 0.5, r + KEY_H, KEY_W, z - 0.5, z + SPIGOT_L - 2)
    return body + rib


def socket(z: float) -> m3.Manifold:
    """Keyed recess in the bottom of a segment at height z; 45-degree ceiling so it prints without support."""
    r = SPIGOT_OD / 2 + JOINT_CLEAR
    depth = SPIGOT_L + 0.5
    cone_h = r - BORE_D / 2
    hole = cyl(r, z - 1, z + depth) + cyl(r, z + depth, z + depth + cone_h, BORE_D / 2)
    groove = key(r - 1, r + KEY_H + JOINT_CLEAR, KEY_W + 2 * JOINT_CLEAR, z - 1, z + depth)
    # the groove's top would be a short bridge: give it a 45-degree roof instead
    r_out, w = r + KEY_H + JOINT_CLEAR, KEY_W + 2 * JOINT_CLEAR
    lead = m3.Manifold.hull(key(r - 1, r_out, w, z + depth - 0.01, z + depth)
                            + key(r - 1, r - 0.99, w, z + depth + r_out - r + 0.99, z + depth + r_out - r + 1))
    return hole + groove + lead


def joints() -> list[float]:
    shaft_h = TOTAL_H - HEAD_H
    return [shaft_h * i / SHAFT_SEGMENTS for i in range(SHAFT_SEGMENTS + 1)]


def head_base_radius(z: np.ndarray) -> np.ndarray:
    """Shaft radius that flares into the cup in the head piece."""
    z_head = TOTAL_H - HEAD_H
    cup_r = WAND_D / 2 + WAND_CLEAR + CUP_WALL + 1.5
    t = np.clip((z - (z_head + 40)) / 70.0, 0, 1)
    return R0 + (cup_r - R0) * (3 * t**2 - 2 * t**3)


def cup_top() -> float:
    return TOTAL_H - HEAD_H + 40 + 70 + WAND_DEPTH - 10


def shaft_segment(i: int) -> trimesh.Trimesh:
    zs = joints()
    z0, z1 = zs[i], zs[i + 1]
    solid = to_m(loft(z0, z1, radius))
    solid = solid + spigot(z1)
    cut = cyl(BORE_D / 2, z0 + (FOOT_T if i == 0 else -1), z1 + SPIGOT_L + 1)
    if i > 0:
        cut = cut + socket(z0)
    return to_t(solid - cut)


def branch_path(k: int) -> np.ndarray:
    """Centerline of one branch: rises from the cup's side, leans out, then curls back in a little."""
    zb = cup_top() - 25
    a0 = 2 * np.pi * k / BRANCHES + 0.3
    pts = []
    r_base = WAND_D / 2 + WAND_CLEAR + CUP_WALL - 1.0
    # root: starts buried in the cup wall 35 mm lower and grows out at a shallow angle (no overhang)
    for t in np.linspace(0, 1, 6, endpoint=False):
        pts.append(((r_base - 6 + 6 * t) * np.cos(a0), (r_base - 6 + 6 * t) * np.sin(a0), zb - 35 * (1 - t)))
    for t in np.linspace(0, 1, 24):
        z = zb + t * (TOTAL_H - BRANCH_R1 - zb)
        r = r_base + 9.0 * np.sin(np.pi * 0.8 * t) - 3.0 * t**3   # leans out, tips curl back in
        a = a0 + 1.1 * t                                         # twists around the cup
        pts.append((r * np.cos(a), r * np.sin(a), z))
    return np.array(pts)


def head() -> trimesh.Trimesh:
    z0 = TOTAL_H - HEAD_H
    ct = cup_top()
    solid = to_m(loft(z0, ct, lambda T, Z: radius(T, Z, head_base_radius(Z))))
    for k in range(BRANCHES):
        pts = branch_path(k)
        rs = np.interp(np.arange(len(pts)), [0, 6, len(pts) - 1], [BRANCH_R0, BRANCH_R0, BRANCH_R1])
        for (p, r), (q, s) in zip(zip(pts[:-1], rs[:-1]), zip(pts[1:], rs[1:])):
            a = m3.Manifold.sphere(r, 24).translate(tuple(p))
            b = m3.Manifold.sphere(s, 24).translate(tuple(q))
            solid = solid + m3.Manifold.hull(a + b)
    wand_r = WAND_D / 2 + WAND_CLEAR
    cut = (socket(z0) + cyl(BORE_D / 2, z0, z0 + PIPE_INTO_HEAD)
           + cyl(wand_r, ct - WAND_DEPTH, TOTAL_H + 10)
           # 45-degree floor under the wand cup so the cup's floor prints over the bore without support
           + cyl(BORE_D / 2, z0 + PIPE_INTO_HEAD, z0 + PIPE_INTO_HEAD + 1.0)
           + cyl(BORE_D / 2, z0 + PIPE_INTO_HEAD + 1.0, z0 + PIPE_INTO_HEAD + 1.0 + BORE_D / 2, 0.01))
    return to_t(solid - cut)


def pieces() -> list[tuple[str, trimesh.Trimesh]]:
    out = [(f"segment-{i + 1}{'-foot' if i == 0 else ''}", shaft_segment(i)) for i in range(SHAFT_SEGMENTS)]
    out.append((f"segment-{SHAFT_SEGMENTS + 1}-head", head()))
    return out


def min_wall() -> float:
    """Thinnest shaft wall around the bore (sampled), and at the socket's key groove."""
    th = np.linspace(0, 2 * np.pi, 720, endpoint=False)
    zs = np.arange(0, TOTAL_H - HEAD_H, 1.0)
    T, Z = np.meshgrid(th, zs)
    return float(radius(T, Z).min() - BORE_D / 2)


def check(parts) -> dict:
    zs = joints()
    info = {
        "pieces": {}, "joints_mm": [round(z, 1) for z in zs[1:]],
        "pvc": {"od_mm": PVC_OD, "bore_mm": BORE_D, "clearance_per_side_mm": round((BORE_D - PVC_OD) / 2, 2),
                "pipe_length_mm": round(TOTAL_H - HEAD_H + PIPE_INTO_HEAD - FOOT_T - 3.0, 0),
                "pipe_length_in": round((TOTAL_H - HEAD_H + PIPE_INTO_HEAD - FOOT_T - 3.0) / 25.4, 2)},
        "min_shaft_wall_around_bore_mm": round(min_wall(), 2),
        "socket_wall_min_mm": round(R_MIN - (SPIGOT_OD / 2 + JOINT_CLEAR + KEY_H), 2),
        "wand_cup_mm": {"inside_d": round(WAND_D + 2 * WAND_CLEAR, 2), "depth": WAND_DEPTH,
                        "note": "placeholder size: measure the bubble maker"},
    }
    for name, m in parts:
        p = m.copy()
        n, c, a = p.face_normals, p.triangles_center, p.area_faces
        z_bed = p.bounds[0][2]
        over = (n[:, 2] < -np.cos(np.radians(45))) & (c[:, 2] > z_bed + 0.3)
        info["pieces"][name] = {
            "height_mm": round(float(p.extents[2]), 1),
            "footprint_mm": [round(float(v), 1) for v in p.extents[:2]],
            "fits_print_height": bool(p.extents[2] <= MAX_PRINT_H),
            "watertight": bool(p.is_watertight),
            "bodies": len(p.split(only_watertight=False)),
            "volume_cm3": round(float(p.volume) / 1000, 1),
            "overhang_mm2_steeper_than_45": round(float(a[over].sum()), 1),
        }
    # Assembled: neighbours must not overlap (spigot sits in socket with clearance).
    overl = {}
    for (na, a), (nb, b) in itertools.pairwise(parts):
        inter = trimesh.boolean.intersection([a, b], engine="manifold")
        overl[f"{na} / {nb}"] = round(float(inter.volume), 4) if len(inter.faces) else 0.0
    info["assembled_overlap_mm3"] = overl
    pipe = cyl(PVC_OD / 2, FOOT_T + 1, TOTAL_H - HEAD_H + PIPE_INTO_HEAD - 2)
    hit = sum(float((to_m(m) ^ pipe).volume()) for _, m in parts)
    info["pvc_pipe_hits_print_mm3"] = round(hit, 4)
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Segmented wizard's staff with a PVC core")
    ap.add_argument("--out", type=Path, default=Path("output/cad-wizard-staff"))
    args = ap.parse_args(argv)
    parts = pieces()
    info = check(parts)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    for name, m in parts:
        on_bed = m.copy()
        on_bed.apply_translation([0, 0, -on_bed.bounds[0][2]])
        on_bed.export(out / f"{name}.stl")
        on_bed.export(out / f"{name}.3mf")
    rgb = printprep.hex_to_rgb(["#6B4A2E", "#7E5A38"])
    tri = np.concatenate([m.triangles for _, m in parts])
    cols = np.concatenate([np.tile(rgb[i % 2], (len(m.faces), 1)) for i, (_, m) in enumerate(parts)])
    printprep.render_colored_faces(tri, cols, out / "staff.png", "Wizard's staff (segments alternate shade)",
                                   views=((0, "Front"), (-60, "Turned")), px_per_mm=0.55)
    z_head = TOTAL_H - HEAD_H
    sel = [m.slice_plane([0, 0, z_head - 80], [0, 0, 1], cap=True) for _, m in parts[-2:]]
    tri = np.concatenate([m.triangles for m in sel])
    cols = np.concatenate([np.tile(rgb[(len(parts) - 2 + i) % 2], (len(m.faces), 1)) for i, m in enumerate(sel)])
    printprep.render_colored_faces(tri, cols, out / "head.png", "Head with the wand cup",
                                   views=((0, "Front"), (-35, "Angled")), px_per_mm=3)
    zj = joints()[2]
    near = []
    for i, (_, m) in enumerate(parts):
        cut = m.slice_plane([0, 0, zj - 110], [0, 0, 1], cap=True).slice_plane([0, 0, zj + 110], [0, 0, -1], cap=True)
        if len(cut.faces):
            near.append((i, cut))
    tri = np.concatenate([m.triangles for _, m in near])
    cols = np.concatenate([np.tile(rgb[i % 2], (len(m.faces), 1)) for i, m in near])
    printprep.render_colored_faces(tri, cols, out / "joint.png",
                                   "Bark detail across a joint (pattern continues)",
                                   views=((0, "Front"), (-90, "Side")), px_per_mm=3)
    # Cut-away of the same joint with the PVC pipe: keep the back half (y > 0), seen from the front.
    pipe = to_t(cyl(PVC_OD / 2, FOOT_T + 1, TOTAL_H - HEAD_H + PIPE_INTO_HEAD - 2))
    halves = [(i % 2, m.slice_plane([0, 0, 0], [0, 1, 0], cap=True)) for i, m in near]
    halves.append((2, pipe.slice_plane([0, 0, zj - 110], [0, 0, 1], cap=True)
                   .slice_plane([0, 0, zj + 110], [0, 0, -1], cap=True).slice_plane([0, 0, 0], [0, 1, 0], cap=True)))
    shades = printprep.hex_to_rgb(["#6B4A2E", "#9C7550", "#E8E8E8"])
    tri = np.concatenate([m.triangles for _, m in halves])
    cols = np.concatenate([np.tile(shades[i], (len(m.faces), 1)) for i, m in halves])
    printprep.render_colored_faces(tri, cols, out / "joint-section.png",
                                   "Joint cut open (PVC pipe in white)",
                                   views=((0, "Section"),), px_per_mm=4)
    (out / "report.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
