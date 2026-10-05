"""Local, credit-free preparation of a mesh for FDM printing.

Meshy returns GLB files, which follow glTF conventions: meters and Y-up.
Slicers expect STL/3MF in millimeters with Z-up. This module orients the mesh,
scales it to an explicit size in mm, sits it on the build plate (z = 0),
and exports STL/3MF.
"""

from __future__ import annotations

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


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """Load any trimesh-supported file as a single mesh with scene transforms applied."""
    loaded = trimesh.load(str(path))
    if isinstance(loaded, trimesh.Scene):
        if not loaded.geometry:
            raise ValueError(f"{path} contains no geometry")
        loaded = loaded.to_geometry()
    if not isinstance(loaded, trimesh.Trimesh) or len(loaded.faces) == 0:
        raise ValueError(f"{path} did not load as a triangle mesh")
    return loaded


def default_up_axis(path: str | Path) -> str:
    return "y" if Path(path).suffix.lower() in (".glb", ".gltf") else "z"


def prepare(
    mesh: trimesh.Trimesh,
    size_mm: float,
    size_axis: str = "height",
    up_axis: str = "y",
) -> trimesh.Trimesh:
    """Return a copy oriented Z-up, uniformly scaled, centered in XY, resting on z = 0.

    size_axis="height" sets the Z extent; size_axis="longest" sets the largest extent.
    """
    if size_mm <= 0:
        raise ValueError("size_mm must be positive")
    if size_axis not in ("height", "longest"):
        raise ValueError("size_axis must be 'height' or 'longest'")
    if up_axis not in ("y", "z"):
        raise ValueError("up_axis must be 'y' or 'z'")

    out = mesh.copy()
    if up_axis == "y":
        out.apply_transform(Y_UP_TO_Z_UP)

    current = out.extents[2] if size_axis == "height" else out.extents.max()
    if current <= 0:
        raise ValueError("mesh has zero size along the requested axis")
    out.apply_scale(size_mm / current)

    lo, hi = out.bounds
    out.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    return out


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


def render_preview(mesh: trimesh.Trimesh, path: Path, max_faces: int = 60000) -> Path:
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
