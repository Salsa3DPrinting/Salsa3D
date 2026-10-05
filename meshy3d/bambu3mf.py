"""Write a multi-part, multi-filament 3MF in Bambu Studio's project layout.

One printable object made of several parts; each part is assigned to a filament slot, which is how
Bambu Studio stores "add part -> set filament" models. The layout mirrors the Bambu Studio 2.3 3MF
that Meshy's multi-color endpoint returns (3D/3dmodel.model -> components in
3D/Objects/object_1.model, part settings in Metadata/model_settings.config, filament list in
Metadata/project_settings.config). It has not been opened in Bambu Studio from this environment,
so check the part/filament list after loading.
"""

from __future__ import annotations

import json
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

import numpy as np
import trimesh

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
BAMBU_NS = "http://schemas.bambulab.com/package/2021"
IDENTITY_3MF = "1 0 0 0 1 0 0 0 1 0 0 0"
IDENTITY_4X4 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"


@dataclass
class Part:
    name: str
    mesh: trimesh.Trimesh
    filament: int  # 1-based filament slot; used for any triangle without a paint code
    # Optional Bambu per-triangle paint codes (e.g. from Meshy's multi-color 3MF), one per face.
    paint: list[str] | None = None


def _mesh_xml(object_id: int, mesh: trimesh.Trimesh, paint: list[str] | None = None) -> str:
    verts = "\n".join(f'     <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in mesh.vertices)
    if paint is not None and len(paint) != len(mesh.faces):
        raise ValueError(f"{len(paint)} paint codes for {len(mesh.faces)} faces")
    codes = paint or [""] * len(mesh.faces)
    tris = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"' + (f' paint_color="{code}"' if code else "") + "/>"
                     for (a, b, c), code in zip(mesh.faces, codes))
    return (f'  <object id="{object_id}" p:UUID="{uuid.uuid4()}" type="model">\n   <mesh>\n    <vertices>\n'
            f"{verts}\n    </vertices>\n    <triangles>\n{tris}\n    </triangles>\n   </mesh>\n  </object>")


def project_settings(palette: list[str], printer: str = "Bambu Lab X1 Carbon", nozzle: str = "0.4") -> dict:
    n = len(palette)
    per = lambda value: [value] * n
    return {
        "filament_colour": [c.upper() + ("FF" if len(c) == 7 else "") for c in palette],
        "filament_settings_id": per("Bambu PLA Basic @BBL X1C"),
        "filament_type": per("PLA"),
        "filament_diameter": per("1.75"),
        "enable_prime_tower": "1",
        "single_extruder_multi_material": "1",
        "print_sequence": "by layer",
        "printer_model": printer,
        "printer_settings_id": f"{printer} {nozzle} nozzle",
        "nozzle_diameter": [nozzle],
        "print_settings_id": "0.20mm Standard @BBL X1C",
        "from": "project",
        "name": "project_settings",
        "version": "02.03.01.00",
    }


def write(parts: list[Part], palette: list[str], path: Path, name: str = "model",
          bed_center: tuple[float, float] = (128.0, 128.0)) -> Path:
    """Write parts as one object. Coordinates are mm with Z up; the object is placed at bed_center."""
    if not parts:
        raise ValueError("no parts")
    for p in parts:
        if not 1 <= p.filament <= len(palette):
            raise ValueError(f"part {p.name} uses filament {p.filament}, palette has {len(palette)}")
    lo = np.min([p.mesh.bounds[0] for p in parts], axis=0)
    hi = np.max([p.mesh.bounds[1] for p in parts], axis=0)
    # Center the object in XY on its own origin with its base at z=0; the build item moves it on the bed.
    offset = np.array([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    meshes = [p.mesh.copy().apply_translation(offset) for p in parts]

    obj_file = "/3D/Objects/object_1.model"
    assembly_id = len(parts) + 1
    objects_xml = "\n".join(_mesh_xml(i, m, p.paint) for i, (p, m) in enumerate(zip(parts, meshes), 1))
    sub_model = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
                 f'xmlns="{CORE_NS}" xmlns:BambuStudio="{BAMBU_NS}" xmlns:p="{PROD_NS}" requiredextensions="p">\n'
                 f' <metadata name="BambuStudio:3mfVersion">2</metadata>\n <resources>\n{objects_xml}\n'
                 f" </resources>\n <build/>\n</model>\n")
    components = "\n".join(
        f'    <component p:path="{obj_file}" objectid="{i}" p:UUID="{uuid.uuid4()}" transform="{IDENTITY_3MF}"/>'
        for i in range(1, len(parts) + 1)
    )
    cx, cy = bed_center
    root_model = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
                  f'xmlns="{CORE_NS}" xmlns:BambuStudio="{BAMBU_NS}" xmlns:p="{PROD_NS}" requiredextensions="p">\n'
                  f' <metadata name="Application">BambuStudio-02.03.01.00</metadata>\n'
                  f' <metadata name="BambuStudio:3mfVersion">2</metadata>\n <resources>\n'
                  f'  <object id="{assembly_id}" p:UUID="{uuid.uuid4()}" type="model">\n   <components>\n'
                  f"{components}\n   </components>\n  </object>\n </resources>\n"
                  f' <build p:UUID="{uuid.uuid4()}">\n'
                  f'  <item objectid="{assembly_id}" p:UUID="{uuid.uuid4()}" '
                  f'transform="1 0 0 0 1 0 0 0 1 {cx:g} {cy:g} 0" printable="1"/>\n </build>\n</model>\n')
    part_cfg = "\n".join(
        f'    <part id="{i}" subtype="normal_part">\n'
        f'      <metadata key="name" value={quoteattr(p.name)}/>\n'
        f'      <metadata key="matrix" value="{IDENTITY_4X4}"/>\n'
        f'      <metadata key="extruder" value="{p.filament}"/>\n'
        f'      <mesh_stat face_count="{len(m.faces)}" edges_fixed="0" degenerate_facets="0" '
        f'facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n    </part>'
        for i, (p, m) in enumerate(zip(parts, meshes), 1)
    )
    model_settings = (f'<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <object id="{assembly_id}">\n'
                      f"    <metadata key=\"name\" value={quoteattr(name)}/>\n"
                      f'    <metadata key="extruder" value="1"/>\n{part_cfg}\n  </object>\n'
                      f'  <plate>\n    <metadata key="plater_id" value="1"/>\n    <model_instance>\n'
                      f'      <metadata key="object_id" value="{assembly_id}"/>\n'
                      f'      <metadata key="instance_id" value="0"/>\n'
                      f'      <metadata key="identify_id" value="1"/>\n    </model_instance>\n  </plate>\n'
                      f"</config>\n")
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/'
                     'package/2006/content-types">\n <Default Extension="rels" ContentType="application/'
                     'vnd.openxmlformats-package.relationships+xml"/>\n <Default Extension="model" '
                     'ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n</Types>\n')
    rel = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/'
           'package/2006/relationships">\n <Relationship Target="{}" Id="rel-1" Type="http://schemas.'
           'microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>\n')

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rel.format("/3D/3dmodel.model"))
        z.writestr("3D/_rels/3dmodel.model.rels", rel.format(obj_file))
        z.writestr("3D/3dmodel.model", root_model)
        z.writestr("3D/Objects/object_1.model", sub_model)
        z.writestr("Metadata/model_settings.config", model_settings)
        z.writestr("Metadata/project_settings.config", json.dumps(project_settings(palette), indent=4))
    return path


def read_parts(path: Path) -> list[dict]:
    """Read back part names, filament slots and meshes (for checks and previews)."""
    import re

    with zipfile.ZipFile(path) as z:
        cfg = z.read("Metadata/model_settings.config").decode()
        sub = z.read("3D/Objects/object_1.model").decode()
    filaments = {int(i): (n, int(e)) for i, n, e in re.findall(
        r'<part id="(\d+)"[^>]*>\s*<metadata key="name" value="([^"]*)"/>.*?key="extruder" value="(\d+)"', cfg, re.DOTALL)}
    out = []
    for oid, body in re.findall(r'<object id="(\d+)"[^>]*>(.*?)</object>', sub, re.DOTALL):
        v = np.array(re.findall(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"', body), dtype=float)
        f = np.array(re.findall(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"', body), dtype=int)
        name, filament = filaments[int(oid)]
        out.append({"name": name, "filament": filament, "mesh": trimesh.Trimesh(v, f, process=False)})
    return out


def read_painted(path: Path) -> tuple[trimesh.Trimesh, list[str], list[str]]:
    """Read a single-object painted 3MF (like Meshy's multi-color output).

    Returns (mesh in the object's own coordinates, paint code per face, filament palette as #RRGGBB).
    Face order is preserved so the codes stay aligned.
    """
    import re

    with zipfile.ZipFile(path) as z:
        models = [n for n in z.namelist() if n.endswith(".model")]
        data = max((z.read(n) for n in models), key=len).decode()
        try:
            palette = [c[:7] for c in json.loads(z.read("Metadata/project_settings.config"))["filament_colour"]]
        except (KeyError, ValueError):
            palette = []
    v = np.array(re.findall(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"', data), dtype=float)
    tris = re.findall(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"(?: paint_color="([^"]*)")?', data)
    if not len(v) or not tris:
        raise ValueError(f"{path}: no mesh found")
    faces = np.array([t[:3] for t in tris], dtype=int)
    return trimesh.Trimesh(v, faces, process=False), [t[3] for t in tris], palette


def repaint(src: Path, dst: Path, codes: list[str], palette: list[str] | None = None,
            moved: dict[int, tuple[float, float, float]] | None = None) -> Path:
    """Copy a single-object painted 3MF with new per-triangle paint codes (and optionally new filament
    colors and new positions for some vertices, by index). Everything not changed stays byte-for-byte
    the same, including unmoved vertices and all other files in the package."""
    import re

    with zipfile.ZipFile(src) as zin:
        infos = zin.infolist()
        files = {i.filename: zin.read(i.filename) for i in infos}
    model = max((n for n in files if n.endswith(".model")), key=lambda n: len(files[n]))
    n_tris = len(re.findall(rb"<triangle\b", files[model]))
    if n_tris != len(codes):
        raise ValueError(f"{len(codes)} codes for {n_tris} triangles")
    it = iter(codes)
    count = 0

    def sub(m: re.Match) -> bytes:
        nonlocal count
        count += 1
        code = next(it)
        attrs = re.sub(rb'\s*paint_color="[^"]*"', b"", m.group(1))
        return b"<triangle" + attrs + (f' paint_color="{code}"'.encode() if code else b"") + m.group(2)

    data = re.sub(rb"<triangle\b([^>]*?)(\s*/>)", sub, files[model])
    if count != n_tris:
        raise ValueError(f"rewrote {count} of {n_tris} triangles")
    if moved:
        vidx = -1

        def vsub(m: re.Match) -> bytes:
            nonlocal vidx
            vidx += 1
            if vidx not in moved:
                return m.group(0)
            x, y, z = moved[vidx]
            return f'<vertex x="{x:.6g}" y="{y:.6g}" z="{z:.6g}"/>'.encode()

        data = re.sub(rb"<vertex\b[^>]*/>", vsub, data)
        if max(moved) > vidx:
            raise ValueError(f"vertex index {max(moved)} out of range ({vidx + 1} vertices)")
    files[model] = data
    if palette is not None:
        settings = json.loads(files["Metadata/project_settings.config"])
        settings["filament_colour"] = [c.upper() + ("FF" if len(c) == 7 else "") for c in palette]
        files["Metadata/project_settings.config"] = json.dumps(settings, indent=4).encode()
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in infos:
            zout.writestr(info, files[info.filename])
    return dst
