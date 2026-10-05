"""Meshy Creative Lab: photo -> ready-made printable objects (keychain, figure, lamp, ...).

Most presets have two paid stages: `prototype` turns the photo into a concept image, and
`build` turns that concept into a 3D model. Reviewing the concept before building avoids
paying for a build of a concept nobody wanted. Docs: https://docs.meshy.ai/api/creative-lab-<name>
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import printing, printprep
from .client import MeshyClient, log_stderr
from .pipeline import image_to_url, slugify

PRESET_IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp")


@dataclass(frozen=True)
class Preset:
    name: str
    path: str
    two_stage: bool
    prototype_credits: int  # from https://docs.meshy.ai/api/pricing, checked 2026-10-05
    build_credits: int
    takes_options: bool = False  # build body accepts an "options" object
    takes_output: bool = False  # build body accepts {"output": {"format": ...}}
    prototype_required: tuple[str, ...] = ()
    # How the downloaded result becomes print files:
    #   relief  - flat badge GLB: lay flat, scale longest side to options.size_mm
    #   figure  - textured GLB with no size control: needs a height/longest size from the user
    #   keycap  - GLB already in real-world mm: orient and export, no rescale
    #   as-is   - Meshy already returns STL/3MF: measure and preview only
    post: str = "as-is"
    default_size_mm: float | None = None
    summary: str = ""

    @property
    def doc_url(self) -> str:
        return f"https://docs.meshy.ai/api/creative-lab-{self.name}"


PRESETS: dict[str, Preset] = {
    p.name: p
    for p in [
        Preset("keychain", "/creative-lab/keychain/v1", True, 6, 30, True, True, post="relief",
               default_size_mm=40, summary="Colorized relief medallion; optional engraved name (name_text)"),
        Preset("fridge-magnet", "/creative-lab/fridge-magnet/v1", True, 6, 30, True, True, post="relief",
               default_size_mm=60, summary="Colorized relief with a flat back for a magnet"),
        Preset("figure", "/creative-lab/figure/v1", True, 6, 30, post="figure",
               summary="Chibi-style textured figurine"),
        Preset("vinyl-figure", "/creative-lab/vinyl-figure/v1", True, 6, 30, post="figure",
               summary="Big-head vinyl collectible figure"),
        Preset("brick-figure", "/creative-lab/brick-figure/v1", True, 6, 30, post="figure",
               summary="Brick-style minifigure"),
        Preset("lamp", "/creative-lab/lamp/v1", True, 30, 6, True, True, post="as-is",
               summary="Lampshade STL (+ fixture base); prototype param image_subject=character|landscape"),
        Preset("keycap", "/creative-lab/keycap/v1", True, 12, 50, True, False, post="keycap",
               summary="Cherry MX 1u keycap with a sculpted head, real-world mm"),
        Preset("fidget-pixel", "/creative-lab/fidget-pixel/v1", True, 6, 30, True, True,
               prototype_required=("type",), post="as-is",
               summary="Multi-color pixel-art fidget board as 3MF; prototype param type=person|other"),
        Preset("fidget-collapsible", "/creative-lab/fidget-collapsible/v1", False, 0, 6, post="as-is",
               summary="Print-in-place collapsible ring fidget (single stage, no options)"),
    ]
}

Log = Callable[[str], None]


def get(name: str) -> Preset:
    if name not in PRESETS:
        raise ValueError(f"Unknown preset {name!r}; choose from {', '.join(PRESETS)}")
    return PRESETS[name]


def prototype_payload(preset: Preset, image: str, params: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in preset.prototype_required if k not in params]
    if missing:
        raise ValueError(f"{preset.name} prototype needs: {', '.join(missing)}")
    return {"image_url": image_to_url(image, PRESET_IMAGE_MIMES), **params}


def build_payload(
    preset: Preset, prototype_id: str, options: dict[str, Any], fmt: str | None, candidate_id: str | None
) -> dict[str, Any]:
    if not preset.two_stage:
        raise ValueError(f"{preset.name} has no build stage; use `preset run`")
    body: dict[str, Any] = {"input_task_id": prototype_id}
    if preset.name == "keycap":
        if not candidate_id:
            raise ValueError("keycap build needs a candidate_id from the prototype")
        body["candidate_id"] = candidate_id
    if options:
        if not preset.takes_options:
            raise ValueError(f"{preset.name} build takes no options")
        body["options"] = options
    if fmt:
        if not preset.takes_output:
            raise ValueError(f"{preset.name} build has no output format choice")
        body["output"] = {"format": fmt}
    return body


def new_out_dir(out_root: Path, preset: Preset, image: str) -> Path:
    out_dir = out_root / f"{time.strftime('%Y%m%d-%H%M%S')}-{preset.name}-{slugify(Path(image).stem, 24)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def load_manifest(out_dir: Path) -> dict:
    path = out_dir / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_manifest(out_dir: Path, manifest: dict) -> None:
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


def run_prototype(
    client: MeshyClient, preset: Preset, image: str, params: dict[str, Any], out_root: Path, log: Log = log_stderr
) -> dict:
    """Stage 1: photo -> concept image(s), saved as concept-N.png for review."""
    if not preset.two_stage:
        raise ValueError(f"{preset.name} is single-stage; use `preset run`")
    out_dir = new_out_dir(out_root, preset, image)
    endpoint = f"{preset.path}/prototype"
    log(f"Creating {preset.name} prototype ({preset.prototype_credits} credits)")
    task = client.run_task(endpoint, prototype_payload(preset, image, params), on_progress=_progress(log))
    concepts = [
        str(client.download(url, out_dir / f"concept-{i}.png"))
        for i, url in enumerate(task.get("image_urls") or [], 1)
    ]
    manifest = {
        "preset": preset.name,
        "source": image,
        "steps": {
            "prototype": {
                "task_id": task["id"],
                "params": params,
                "consumed_credits": task.get("consumed_credits"),
                "concepts": concepts,
                "candidate_ids": task.get("candidate_ids"),
                "name_text": task.get("name_text"),
                "expires_at": task.get("expires_at"),
            }
        },
        "credits_consumed": task.get("consumed_credits") or 0,
        "output_dir": str(out_dir),
    }
    save_manifest(out_dir, manifest)
    return manifest


def run_build(
    client: MeshyClient,
    preset: Preset,
    out_dir: Path,
    prototype_id: str | None = None,
    options: dict[str, Any] | None = None,
    fmt: str | None = None,
    candidate_id: str | None = None,
    size_mm: float | None = None,
    size_axis: str = "height",
    flip: bool = False,
    multicolor: printing.MultiColorOptions | None = None,
    log: Log = log_stderr,
) -> dict:
    """Stage 2: concept -> 3D model, downloaded and turned into print files in out_dir."""
    manifest = load_manifest(out_dir) or {"preset": preset.name, "steps": {}, "credits_consumed": 0}
    proto = manifest["steps"].get("prototype", {})
    prototype_id = prototype_id or proto.get("task_id")
    if not prototype_id:
        raise ValueError("No prototype task id: pass one, or a directory from `preset prototype`")
    if preset.name == "keycap" and not candidate_id:
        candidate_id = _first_candidate(client, preset, prototype_id, proto)
    options = options or {}
    _check_post_inputs(preset, size_mm, fmt, multicolor is not None)

    endpoint = f"{preset.path}/build"
    log(f"Building {preset.name} ({preset.build_credits} credits)")
    body = build_payload(preset, prototype_id, options, fmt, candidate_id)
    task = client.run_task(endpoint, body, on_progress=_progress(log))
    return _finish(client, preset, task, body, manifest, out_dir, options, size_mm, size_axis, flip, multicolor, log)


def run_single(
    client: MeshyClient, preset: Preset, image: str, out_root: Path, log: Log = log_stderr
) -> dict:
    """Single-stage presets (fidget-collapsible): photo -> model in one task."""
    if preset.two_stage:
        raise ValueError(f"{preset.name} has two stages; use prototype then build")
    out_dir = new_out_dir(out_root, preset, image)
    manifest = {"preset": preset.name, "source": image, "steps": {}, "credits_consumed": 0}
    log(f"Creating {preset.name} ({preset.build_credits} credits)")
    body = {"image_url": image_to_url(image, PRESET_IMAGE_MIMES)}
    task = client.run_task(preset.path, body, on_progress=_progress(log))
    return _finish(client, preset, task, {}, manifest, out_dir, {}, None, "height", False, None, log)


def _check_post_inputs(preset: Preset, size_mm: float | None, fmt: str | None, multicolor: bool = False) -> None:
    """Fail before any credits are spent on a build whose result we couldn't use."""
    if multicolor:
        if preset.post not in ("relief", "figure", "keycap"):
            raise ValueError(f"{preset.name} doesn't return a textured GLB, so multi-color doesn't apply")
        if fmt and fmt != "glb":
            raise ValueError("Multi-color needs the build's GLB; drop --format or use --format glb")
    if preset.post == "figure" and not size_mm:
        raise ValueError(f"{preset.name} has no size control in Meshy; give --height-mm or --longest-mm")
    if preset.post in ("relief", "keycap") and size_mm:
        raise ValueError(f"{preset.name} is sized by Meshy; use --option size_mm=... (keychain/magnet) instead")


def _first_candidate(client: MeshyClient, preset: Preset, prototype_id: str, proto: dict) -> str:
    candidates = proto.get("candidate_ids")
    if not candidates:
        task, _ = client.get_task(f"{preset.path}/prototype", prototype_id)
        candidates = task.get("candidate_ids") or []
    if not candidates:
        raise ValueError("Keycap prototype has no candidate_ids")
    return candidates[0]


def _finish(
    client: MeshyClient,
    preset: Preset,
    task: dict,
    body: dict,
    manifest: dict,
    out_dir: Path,
    options: dict[str, Any],
    size_mm: float | None,
    size_axis: str,
    flip: bool,
    multicolor: printing.MultiColorOptions | None,
    log: Log,
) -> dict:
    downloads = {}
    for key, url in (task.get("model_urls") or {}).items():
        if url:
            downloads[key] = str(client.download(url, out_dir / _asset_name(key, url)))
    if task.get("thumbnail_url"):
        client.download(task["thumbnail_url"], out_dir / "thumbnail.png")
    step = {
        "task_id": task["id"],
        "request": {k: v for k, v in body.items() if k != "image_url"},
        "consumed_credits": task.get("consumed_credits"),
        "downloads": downloads,
        "expires_at": task.get("expires_at"),
    }
    manifest["steps"]["build"] = step
    manifest["credits_consumed"] = (manifest.get("credits_consumed") or 0) + (task.get("consumed_credits") or 0)
    manifest["output_dir"] = str(out_dir)
    save_manifest(out_dir, manifest)

    step["print"] = _post_process(preset, downloads, out_dir, options, size_mm, size_axis, flip)
    save_manifest(out_dir, manifest)

    glb_url = (task.get("model_urls") or {}).get("glb")
    if multicolor:
        if not glb_url:
            raise ValueError("Multi-color needs the build's GLB; request the glb output format")
        result = printing.run_multicolor(
            client, {"model_url": glb_url}, multicolor, out_dir, size_mm, size_axis, log=log,
            on_progress=_progress(log),
        )
        manifest["steps"]["multicolor"] = result
        manifest["credits_consumed"] += result.get("consumed_credits") or 0
        save_manifest(out_dir, manifest)
    return manifest


def _post_process(
    preset: Preset,
    downloads: dict[str, str],
    out_dir: Path,
    options: dict[str, Any],
    size_mm: float | None,
    size_axis: str,
    flip: bool,
) -> dict:
    glb = downloads.get("glb")
    if preset.post in ("relief", "figure", "keycap") and glb:
        notes = []
        mesh = printprep.load_mesh(glb)
        if preset.post == "relief":
            size = float(options.get("size_mm", preset.default_size_mm))
            prepared = printprep.prepare(mesh, size, "longest", "flat", flip)
            notes.append(f"Laid flat; longest side set to size_mm={size}.")
        elif preset.post == "figure":
            prepared = printprep.prepare(mesh, size_mm, size_axis, "y", flip)
        else:
            prepared = printprep.prepare(mesh, None, up_axis="y", flip=flip)
            if prepared.extents.max() < 1.0:
                # Docs say real-world mm; a sub-1-unit model means the GLB is in meters.
                prepared.apply_scale(1000)
                notes.append("GLB looked like meters (largest side < 1); scaled x1000 to mm.")
        files = printprep.export(prepared, out_dir, "model-print", ["stl", "3mf"])
        preview = printprep.render_preview(prepared, out_dir / "preview.png")
        return {
            "print_files": [str(p) for p in files],
            "preview": str(preview),
            "mesh_report": printprep.report(prepared).to_dict(),
            "notes": notes,
        }

    measured = {}
    for key, path in downloads.items():
        if Path(path).suffix.lower() in (".stl", ".3mf"):
            entry: dict[str, Any] = {"file": path}
            try:
                entry.update(printprep.measure(path))
                stem = Path(path).stem
                entry["preview"] = str(printprep.render_preview(printprep.load_mesh(path), out_dir / f"{stem}-preview.png"))
            except Exception as e:  # noqa: BLE001 - measuring Meshy's own files is best-effort
                entry["measure_error"] = str(e)
            measured[key] = entry
    return {"print_files": [m["file"] for m in measured.values()], "measured": measured,
            "notes": ["Meshy produced these print files directly; they were not rescaled."]}


def _asset_name(key: str, url: str) -> str:
    suffix = Path(urlparse(url).path).suffix or ".bin"
    return f"model{suffix}" if key == suffix.lstrip(".") else f"{key}{suffix}"


def _progress(log: Log) -> Callable[[dict], None]:
    last: list = [None]

    def progress(task: dict) -> None:
        state = (task.get("status"), task.get("progress", 0))
        if state != last[0]:
            last[0] = state
            log(f"  {state[0]} {state[1]}%")

    return progress
