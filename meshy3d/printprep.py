"""Local, credit-free preparation of a mesh for FDM printing.

Meshy returns GLB files, which follow glTF conventions: meters and Y-up.
Slicers expect STL/3MF in millimeters with Z-up. This module orients the mesh,
scales it to an explicit size in mm, sits it on the build plate (z = 0),
and exports STL/3MF.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import trimesh

SUPPORTED_EXPORTS = ("stl", "3mf")

# Rotate +90 deg about X: maps glTF's +Y (up) onto +Z (up).
Y_UP_TO_Z_UP = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])


@dataclass
class MeshReport:
    extents_mm: list[float]
    is_watertight: bool
    volume_cm3: float | None
    faces: int
    bodies: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def geometry_only(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Drop textures/colors and merge duplicate vertices.

    Textured models duplicate vertices along UV seams. Left as-is, the mesh reads as many
    disconnected open pieces: not watertight, and splitting it copies the texture per piece
    (this exhausted memory on a 225k-face Meshy model). Printing only needs the geometry.
    """
    return trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces, process=True)


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """Load any trimesh-supported file as one geometry-only mesh with scene transforms applied."""
    loaded = trimesh.load(str(path))
    if isinstance(loaded, trimesh.Scene):
        if not loaded.geometry:
            raise ValueError(f"{path} contains no geometry")
        loaded = loaded.to_geometry()
    if not isinstance(loaded, trimesh.Trimesh) or len(loaded.faces) == 0:
        raise ValueError(f"{path} did not load as a triangle mesh")
    return geometry_only(loaded)


def default_up_axis(path: str | Path) -> str:
    return "y" if Path(path).suffix.lower() in (".glb", ".gltf") else "z"


ORIENTATIONS = ("y", "z", "flat")


def orient(mesh: trimesh.Trimesh, up_axis: str, flip: bool = False) -> trimesh.Trimesh:
    """Return a Z-up copy. up_axis "flat" lays the thinnest dimension along Z (reliefs, badges)."""
    if up_axis not in ORIENTATIONS:
        raise ValueError(f"up_axis must be one of {ORIENTATIONS}")
    out = mesh.copy()
    if up_axis == "y":
        out.apply_transform(Y_UP_TO_Z_UP)
    elif up_axis == "flat":
        thinnest = int(np.argmin(out.extents))
        if thinnest == 0:
            out.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
        elif thinnest == 1:
            out.apply_transform(Y_UP_TO_Z_UP)
    if flip:
        out.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))
    return out


def scale_factor(extents: np.ndarray, size_mm: float, size_axis: str) -> float:
    if size_mm <= 0:
        raise ValueError("size_mm must be positive")
    if size_axis not in ("height", "longest"):
        raise ValueError("size_axis must be 'height' or 'longest'")
    current = extents[2] if size_axis == "height" else extents.max()
    if current <= 0:
        raise ValueError("mesh has zero size along the requested axis")
    return size_mm / float(current)


def place_on_bed(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    lo, hi = mesh.bounds
    mesh.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    return mesh


def prepare(
    mesh: trimesh.Trimesh,
    size_mm: float | None,
    size_axis: str = "height",
    up_axis: str = "y",
    flip: bool = False,
) -> trimesh.Trimesh:
    """Return a copy oriented Z-up, uniformly scaled, centered in XY, resting on z = 0.

    size_axis="height" sets the Z extent; size_axis="longest" sets the largest extent.
    size_mm=None keeps the file's own units (for outputs Meshy already sized in mm).
    """
    out = orient(mesh, up_axis, flip)
    if size_mm is not None:
        out.apply_scale(scale_factor(out.extents, size_mm, size_axis))
    return place_on_bed(out)


def load_parts(path: str | Path) -> list[tuple[str, trimesh.Trimesh]]:
    """Load a multi-object file (e.g. a split GLB) as named parts, transforms applied."""
    loaded = trimesh.load(str(path))
    if isinstance(loaded, trimesh.Trimesh):
        return [("part-1", loaded)]
    parts = []
    for node in loaded.graph.nodes_geometry:
        transform, geom_name = loaded.graph[node]
        geom = loaded.geometry[geom_name]
        if isinstance(geom, trimesh.Trimesh) and len(geom.faces):
            parts.append((str(node), geometry_only(geom).apply_transform(transform)))
    if not parts:
        raise ValueError(f"{path} contains no mesh parts")
    return parts


def prepare_parts(
    parts: list[tuple[str, trimesh.Trimesh]],
    size_mm: float,
    size_axis: str = "height",
    up_axis: str = "y",
    gap_mm: float = 5.0,
) -> list[tuple[str, trimesh.Trimesh]]:
    """Scale the assembled model to size, then put every part on the bed in a row along X.

    Scaling uses the assembled extents, so the parts fit back together at the requested size.
    Parts keep their assembled orientation; the slicer can rotate them for printing.
    """
    oriented = [(name, orient(m, up_axis)) for name, m in parts]
    assembled = trimesh.util.concatenate([m for _, m in oriented])
    factor = scale_factor(assembled.extents, size_mm, size_axis)
    out, cursor = [], 0.0
    for name, m in oriented:
        m.apply_scale(factor)
        lo, hi = m.bounds
        m.apply_translation([cursor - lo[0], -(lo[1] + hi[1]) / 2, -lo[2]])
        cursor += (hi[0] - lo[0]) + gap_mm
        out.append((name, m))
    return out


def export_parts(parts: list[tuple[str, trimesh.Trimesh]], out_dir: Path) -> dict[str, list[Path] | Path]:
    """One STL per part plus a single 3MF holding every part as its own object."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stls, scene = [], trimesh.Scene()
    for i, (name, m) in enumerate(parts, 1):
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "part"
        path = out_dir / f"part-{i:02d}-{safe}.stl"
        m.export(str(path), file_type="stl")
        stls.append(path)
        scene.add_geometry(m, node_name=f"{i:02d}-{safe}", geom_name=f"{i:02d}-{safe}")
    three_mf = out_dir / "parts.3mf"
    scene.export(str(three_mf), file_type="3mf")
    return {"stl": stls, "3mf": three_mf}


def measure(path: str | Path) -> dict:
    """Extents and object count of a file as-is, without changing it (e.g. Meshy-made 3MF)."""
    loaded = trimesh.load(str(path))
    objects = len(loaded.geometry) if isinstance(loaded, trimesh.Scene) else 1
    return {"extents": [round(float(x), 3) for x in loaded.extents], "objects": objects}


def report(mesh: trimesh.Trimesh) -> MeshReport:
    """Inspect a mesh already in millimeters."""
    watertight = bool(mesh.is_watertight)
    bodies = len(mesh.split(only_watertight=False))
    warnings = []
    if not watertight:
        warnings.append("Mesh is not watertight; slicers may produce gaps or fail.")
    if bodies > 1:
        warnings.append(f"Mesh has {bodies} separate bodies; check for floating parts.")
    if min(mesh.extents) < 1.0:
        warnings.append("Smallest dimension is under 1 mm; likely too thin for FDM.")
    return MeshReport(
        extents_mm=[round(float(x), 2) for x in mesh.extents],
        is_watertight=watertight,
        volume_cm3=round(float(mesh.volume) / 1000, 3) if watertight else None,
        faces=len(mesh.faces),
        bodies=bodies,
        warnings=warnings,
    )


def export(mesh: trimesh.Trimesh, out_dir: Path, stem: str, formats: list[str]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for fmt in formats:
        if fmt not in SUPPORTED_EXPORTS:
            raise ValueError(f"Unsupported export format {fmt!r}; choose from {SUPPORTED_EXPORTS}")
        path = out_dir / f"{stem}.{fmt}"
        mesh.export(str(path), file_type=fmt)
        paths.append(path)
    return paths


_VERTEX = re.compile(rb"<vertex\b[^>]*>")
_COORD = re.compile(rb'\b([xyz])="([^"]+)"')


def scale_3mf(src: Path, dst: Path, factor: float) -> Path:
    """Copy a 3MF with every mesh vertex scaled about the origin; all other content is untouched.

    Used for Meshy's multi-color 3MF so per-triangle paint colors and slicer settings survive.
    """
    import zipfile

    if factor <= 0:
        raise ValueError("factor must be positive")

    def scale_vertex(match: re.Match) -> bytes:
        return _COORD.sub(lambda c: c.group(1) + b'="' + f"{float(c.group(2)) * factor:.9g}".encode() + b'"',
                          match.group(0))

    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.endswith(".model"):
                data = _VERTEX.sub(scale_vertex, data)
            zout.writestr(info, data)
    return dst


def render_preview(mesh: trimesh.Trimesh, path: Path, max_faces: int = 500_000) -> Path:
    """Save front, side and isometric views (mm grid, build plate at z = 0) to a PNG."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    if len(mesh.faces) > max_faces:
        idx = np.random.default_rng(0).choice(len(mesh.faces), max_faces, replace=False)
        tris, normals = mesh.triangles[idx], mesh.face_normals[idx]
    else:
        tris, normals = mesh.triangles, mesh.face_normals
    lo, hi = mesh.bounds
    pad = 0.05 * float(mesh.extents.max())

    fig = plt.figure(figsize=(12, 4.2))
    for i, (title, axes) in enumerate([("Front (X-Z)", (0, 2)), ("Side (Y-Z)", (1, 2))]):
        ax = fig.add_subplot(1, 3, i + 1)
        ax.add_collection(PolyCollection(tris[:, :, axes], facecolor="#4a7ab5", edgecolor="none"))
        ax.axhline(0, color="#c0392b", lw=1.5)
        ax.set_xlim(lo[axes[0]] - pad, hi[axes[0]] + pad)
        ax.set_ylim(min(lo[2], 0) - pad, hi[2] + pad)
        ax.set_aspect("equal")
        ax.set_title(f"{title}, mm")
        ax.grid(alpha=0.3)

    ax = fig.add_subplot(1, 3, 3, projection="3d")
    shade = 0.35 + 0.65 * np.clip(normals @ np.array([0.4, -0.5, 0.75]) / np.linalg.norm([0.4, -0.5, 0.75]), 0, 1)
    ax.add_collection3d(Poly3DCollection(tris, facecolors=plt.cm.Blues(0.3 + 0.6 * shade), edgecolor="none"))
    center, r = (lo + hi) / 2, float(mesh.extents.max()) / 2
    ax.set_xlim(center[0] - r, center[0] + r)
    ax.set_ylim(center[1] - r, center[1] + r)
    ax.set_zlim(0, 2 * r)
    ax.set_box_aspect((1, 1, 1))
    ax.set_title("Isometric")

    ext = mesh.extents
    fig.suptitle(f"{ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm (red line = build plate)")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def hex_to_rgb(palette: list[str]) -> np.ndarray:
    return np.array([[int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)] for c in palette])


def zbuffer(tri2d: np.ndarray, depth: np.ndarray, colors: np.ndarray, px_per_mm: float,
            bg: float = 1.0) -> np.ndarray:
    """Rasterize projected triangles with a depth buffer (smaller depth = nearer). Returns an RGB image.

    tri2d: (N,3,2) screen coords in mm (x right, y up); depth: (N,3); colors: (N,3) in 0-1.
    """
    lo = tri2d.reshape(-1, 2).min(axis=0) - 2
    hi = tri2d.reshape(-1, 2).max(axis=0) + 2
    w, h = (np.ceil((hi - lo) * px_per_mm)).astype(int) + 1
    img = np.full((h, w, 3), bg)
    zbuf = np.full((h, w), np.inf)
    pts = (tri2d - lo) * px_per_mm
    pts[:, :, 1] = h - 1 - pts[:, :, 1]
    for (a, b, c), (za, zb, zc), col in zip(pts, depth, colors):
        x0, y0 = np.floor(np.minimum(np.minimum(a, b), c)).astype(int)
        x1, y1 = np.ceil(np.maximum(np.maximum(a, b), c)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w - 1), min(y1, h - 1)
        if x1 < x0 or y1 < y0:
            continue
        area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(area) < 1e-9:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((b[0] - xs) * (c[1] - ys) - (b[1] - ys) * (c[0] - xs)) / area
        w1 = ((c[0] - xs) * (a[1] - ys) - (c[1] - ys) * (a[0] - xs)) / area
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        z = w0 * za + w1 * zb + w2 * zc
        region = zbuf[y0:y1 + 1, x0:x1 + 1]
        nearer = inside & (z < region)
        region[nearer] = z[nearer]
        img[y0:y1 + 1, x0:x1 + 1][nearer] = col
    return img


def render_colored_faces(tri: np.ndarray, colors: np.ndarray, out_png: Path, title: str,
                         views: tuple[tuple[float, str], ...] = ((0, "Front (-Y)"), (-35, "Front-right 3/4")),
                         px_per_mm: float = 4.0) -> Path:
    """Depth-buffered render of triangles (N,3,3) with per-face RGB colors, viewed from -Y (Z up)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
    light_dir = np.array([-0.35, -0.8, 0.5])
    light_dir /= np.linalg.norm(light_dir)
    fig, axes = plt.subplots(1, len(views), figsize=(5.5 * len(views), 8))
    for ax, (angle, label) in zip(np.atleast_1d(axes), views):
        a = np.radians(angle)
        rot = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
        t, n = tri @ rot.T, normals @ rot.T
        shade = 0.45 + 0.55 * np.abs(n @ light_dir)
        img = zbuffer(t[:, :, [0, 2]], t[:, :, 1], np.clip(colors * shade[:, None], 0, 1), px_per_mm)
        ax.imshow(img)
        ax.set_title(label)
        ax.axis("off")
    fig.suptitle(title)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    return out_png


# Bambu Studio per-triangle paint codes for unsubdivided triangles -> filament number.
# From Bambu/PrusaSlicer's triangle-selector serialization (not documented by Meshy);
# subdivided triangles use longer codes and are counted as "unknown" below.
BAMBU_PAINT_CODES = {"": 1, "4": 1, "8": 2, "0C": 3, "1C": 4, "2C": 5, "3C": 6, "4C": 7, "5C": 8,
                     "6C": 9, "7C": 10, "8C": 11, "9C": 12, "AC": 13, "BC": 14, "CC": 15, "DC": 16}


def render_3mf_colors(path: Path, out_png: Path) -> dict:
    """Render a Bambu-painted 3MF (front and 3/4 views) in its filament colors.

    Returns faces per filament color and the count of paint codes it couldn't map.
    """
    import json
    import zipfile

    with zipfile.ZipFile(path) as z:
        models = [n for n in z.namelist() if n.endswith(".model")]
        data = max((z.read(n) for n in models), key=len)  # the mesh lives in the largest model file
        try:
            settings = json.loads(z.read("Metadata/project_settings.config"))
            palette = [c[:7] for c in settings["filament_colour"]]
        except (KeyError, ValueError):
            palette = ["#888888"]
    verts = np.array(re.findall(rb'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"', data), dtype=float)
    tris = re.findall(rb'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"(?: paint_color="([^"]*)")?', data)
    if not len(verts) or not tris:
        raise ValueError(f"{path}: no mesh found")
    faces = np.array([t[:3] for t in tris], dtype=int)
    codes = [t[3].decode() for t in tris]
    filament = np.array([BAMBU_PAINT_CODES.get(c, 0) for c in codes])
    unknown = int((filament == 0).sum())
    filament[(filament == 0) | (filament > len(palette))] = 1

    colors = hex_to_rgb(palette)[filament - 1]
    render_colored_faces(verts[faces], colors, out_png, f"{Path(path).name} in its filament colors")
    counts = {f"{i}:{palette[i - 1]}": int((filament == i).sum()) for i in range(1, len(palette) + 1)}
    return {"preview": str(out_png), "faces_per_filament": counts, "unknown_paint_codes": unknown}
