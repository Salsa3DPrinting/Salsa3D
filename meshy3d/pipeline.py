"""End-to-end flow: generate with Meshy -> analyze -> (repair) -> local print prep."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import printing, printprep
from .client import (
    IMAGE_TO_3D,
    MULTI_IMAGE_TO_3D,
    PRINT_ANALYZE,
    PRINT_REPAIR,
    TEXT_TO_3D,
    MeshyClient,
    MeshyError,
    log_stderr,
)

# Credits per request, from https://docs.meshy.ai/api/pricing (checked 2026-10-05).
# Meshy can change these; treat the estimate as a guide and check `balance`.
MESH_ONLY_CREDITS = {"latest": 20, "meshy-7.1": 20, "meshy-6": 20, "meshy-6-lite": 5, "meshy-t2": 5}
ULTRA_GEOMETRY_SURCHARGE = 5
REPAIR_CREDITS = 10
# Texture for multi-color: text refine at 2K/4K is 10; image-to-3d with texture is +10 over mesh only.
TEXTURE_CREDITS = 10

REPAIR_MODES = ("auto", "always", "never")

KINDS = ("text", "image", "multi-image")
ENDPOINTS = {"text": TEXT_TO_3D, "image": IMAGE_TO_3D, "multi-image": MULTI_IMAGE_TO_3D}
# Multi-image to 3D accepts these ai_models (no meshy-t2), per its docs.
MULTI_IMAGE_MODELS = ("latest", "meshy-7.1", "meshy-6", "meshy-6-lite")


@dataclass
class GenerateOptions:
    ai_model: str = "latest"
    target_polycount: int | None = None
    negative_prompt: str | None = None
    seed: int | None = None
    geometry_resolution: str | None = None  # "2k"/"4k" = Ultra, +5 credits, needs entitlement


@dataclass
class PrintOptions:
    size_mm: float
    size_axis: str = "height"
    formats: tuple[str, ...] = ("stl", "3mf")
    repair: str = "auto"
    multicolor: printing.MultiColorOptions | None = None
    split: printing.SplitOptions | None = None
    texture_prompt: str | None = None  # text mode + multicolor only


def text_payload(prompt: str, opts: GenerateOptions) -> dict[str, Any]:
    # Preview mode = geometry only. Textures don't matter for single-color FDM.
    payload: dict[str, Any] = {"mode": "preview", "prompt": prompt, "ai_model": opts.ai_model}
    if opts.ai_model == "meshy-t2":
        payload["model_type"] = "smart-topology"
    if opts.negative_prompt:
        payload["negative_prompt"] = opts.negative_prompt
    _add_common(payload, opts)
    return payload


def image_payload(image: str, opts: GenerateOptions, textured: bool = False) -> dict[str, Any]:
    # Texture only when a multi-color 3MF needs it; single-color prints don't.
    payload: dict[str, Any] = {
        "image_url": image_to_url(image),
        "ai_model": opts.ai_model,
        "should_texture": textured,
    }
    if opts.ai_model == "meshy-t2":
        payload["model_type"] = "smart-topology"
    _add_common(payload, opts)
    return payload


def multi_image_payload(images: list[str], opts: GenerateOptions, textured: bool = False) -> dict[str, Any]:
    """1-4 photos of the same object; with latest/meshy-7.1 the first is the front view."""
    if not 1 <= len(images) <= 4:
        raise ValueError("multi-image needs 1 to 4 images")
    payload: dict[str, Any] = {
        "image_urls": [image_to_url(i) for i in images],
        "ai_model": opts.ai_model,
        "should_texture": textured,
    }
    _add_common(payload, opts)
    return payload


def image_task_source(task_id: str) -> dict[str, str]:
    """Use a succeeded Meshy text-to-image / image-to-image task as the input instead of files."""
    return {"image_task_id": task_id}


def generate_payload(
    kind: str, source: str | list[str] | dict[str, str], gen: GenerateOptions, textured: bool
) -> dict[str, Any]:
    if isinstance(source, dict):
        # Image to 3D needs a task with exactly one image; multi-image to 3D takes a task with 1-4
        # (a multi-view task gives 3). Meshy checks the count.
        if kind == "text":
            raise ValueError("an image task id only applies to image or multi-image")
        payload: dict[str, Any] = {"input_task_id": source["image_task_id"], "ai_model": gen.ai_model,
                                   "should_texture": textured}
        if kind == "image" and gen.ai_model == "meshy-t2":
            payload["model_type"] = "smart-topology"
        _add_common(payload, gen)
        return payload
    if kind == "text":
        return text_payload(source, gen)
    if kind == "image":
        return image_payload(source, gen, textured)
    return multi_image_payload(list(source), gen, textured)


def _add_common(payload: dict[str, Any], opts: GenerateOptions) -> None:
    if opts.target_polycount:
        payload["target_polycount"] = opts.target_polycount
    if opts.seed is not None:
        payload["seed"] = opts.seed
    if opts.geometry_resolution:
        payload["geometry_resolution"] = opts.geometry_resolution


IMAGE_TO_3D_MIMES = ("image/png", "image/jpeg")


def image_to_url(image: str, allowed_mimes: tuple[str, ...] = IMAGE_TO_3D_MIMES) -> str:
    """Pass http(s)/data URLs through; turn a local image into a data URI."""
    if re.match(r"^(https?|data):", image):
        return image
    path = Path(image)
    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {image}")
    mime = mimetypes.guess_type(path.name)[0]
    if mime not in allowed_mimes:
        exts = ", ".join(sorted({m.split("/")[1].replace("jpeg", "jpg/jpeg") for m in allowed_mimes}))
        raise ValueError(f"This endpoint accepts {exts} images only, got {path.suffix}")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def validate(kind: str, gen: GenerateOptions, prt: PrintOptions) -> None:
    """Reject combinations Meshy documents as unsupported, before any credits are spent."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if kind == "multi-image":
        if gen.ai_model not in MULTI_IMAGE_MODELS:
            raise ValueError(f"multi-image needs ai_model in {MULTI_IMAGE_MODELS}, not {gen.ai_model}")
        if gen.geometry_resolution == "4k":
            raise ValueError("multi-image supports geometry_resolution 2k or standard, not 4k")
    if prt.split:
        if gen.ai_model not in printing.SPLIT_MODELS:
            raise ValueError(f"Auto split needs ai_model in {printing.SPLIT_MODELS}, not {gen.ai_model}")
        if prt.split.mode == "by_color" and kind == "text":
            raise ValueError("Split mode by_color only works on models generated from an image")
        prt.split.payload("check")
    if prt.multicolor:
        prt.multicolor.payload({})
    if prt.texture_prompt and not (prt.multicolor and kind == "text"):
        raise ValueError("texture_prompt only applies to text mode with multicolor")


def estimate_credits(
    opts: GenerateOptions, repair: str, include_generation: bool = True, prt: PrintOptions | None = None
) -> tuple[int, int]:
    """Return (min, max) credits for one pipeline run. Analyze is free."""
    if opts.ai_model not in MESH_ONLY_CREDITS:
        raise ValueError(f"No price known for ai_model={opts.ai_model!r}")
    base = 0
    if include_generation:
        base = MESH_ONLY_CREDITS[opts.ai_model]
        if opts.geometry_resolution in ("2k", "4k"):
            base += ULTRA_GEOMETRY_SURCHARGE
    extra = 0
    if prt and prt.multicolor:
        # On resume of a text run the texture step still runs; for image it was part of generation.
        extra += printing.MULTICOLOR_CREDITS + (TEXTURE_CREDITS if include_generation else 0)
    if prt and prt.split:
        extra += printing.SPLIT_CREDITS
    low = base + extra + (REPAIR_CREDITS if repair == "always" else 0)
    high = base + extra + (REPAIR_CREDITS if repair != "never" else 0)
    return low, high


def needs_repair(printability: dict | None) -> bool:
    # Meshy's "error" verdict = not watertight, non-positive volume, or non-manifold edges.
    return bool(printability) and printability.get("status") == "error"


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "model"


def new_out_dir(out_root: Path, label: str) -> Path:
    out_dir = out_root / f"{time.strftime('%Y%m%d-%H%M%S')}-{slugify(label)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def run(
    client: MeshyClient,
    kind: str,
    source: str | list[str] | dict[str, str],
    gen: GenerateOptions,
    prt: PrintOptions,
    out_root: Path = Path("output"),
    existing_task_id: str | None = None,
    log: Callable[[str], None] = log_stderr,
) -> dict:
    """Run the full pipeline and return the manifest (also written to manifest.json).

    kind is "text" (source = prompt), "image" (source = path or URL) or "multi-image"
    (source = list of 1-4 paths/URLs of the same object, front view first). For image and
    multi-image, source can also be image_task_source(id) to start from a Meshy image task.
    existing_task_id resumes from an already-created generation task without paying again.
    """
    if prt.repair not in REPAIR_MODES:
        raise ValueError(f"repair must be one of {REPAIR_MODES}")
    validate(kind, gen, prt)
    endpoint = ENDPOINTS[kind]

    if isinstance(source, dict):
        label = f"from-image-task-{source['image_task_id'][:8]}"
    else:
        label = {"text": source, "image": Path(str(source)).stem, "multi-image": Path(str(source[0])).stem}[kind]
    out_dir = new_out_dir(out_root, label)
    manifest: dict[str, Any] = {
        "kind": kind,
        "source": source,
        "generate_options": gen.__dict__,
        "print_options": {
            "size_mm": prt.size_mm,
            "size_axis": prt.size_axis,
            "formats": list(prt.formats),
            "repair": prt.repair,
            "multicolor": prt.multicolor.__dict__ if prt.multicolor else None,
            "split": prt.split.__dict__ if prt.split else None,
        },
        "steps": {},
        "credits_consumed": 0,
    }

    def save() -> None:
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    last_progress: list = [None]

    def progress(task: dict) -> None:
        state = (task.get("status"), task.get("progress", 0))
        if state != last_progress[0]:
            last_progress[0] = state
            log(f"  {state[0]} {state[1]}%")

    # 1. Generate geometry.
    if existing_task_id:
        task_id = existing_task_id
        log(f"Resuming generation task {task_id}")
    else:
        payload = generate_payload(kind, source, gen, textured=prt.multicolor is not None)
        task_id = client.create_task(endpoint, payload)
        log(f"Created {kind}-to-3d task {task_id}")
    manifest["steps"]["generate"] = {"task_id": task_id}
    save()
    gen_task = client.wait_for_task(endpoint, task_id, on_progress=progress)
    # A resumed task was paid for by the earlier run; don't count it again here.
    _record(manifest, "generate", gen_task, count=not existing_task_id)
    if existing_task_id:
        manifest["steps"]["generate"]["resumed"] = True
    model_url = _glb_url(gen_task)
    model_path = client.download(model_url, out_dir / "raw.glb")
    if gen_task.get("thumbnail_url"):
        client.download(gen_task["thumbnail_url"], out_dir / "thumbnail.png")
    save()

    # 2. Analyze printability (free).
    log("Analyzing printability (free)")
    analysis = client.run_task(PRINT_ANALYZE, {"input_task_id": task_id}, on_progress=progress)
    printability = analysis.get("printability")
    manifest["steps"]["analyze"] = {"task_id": analysis["id"], "printability": printability}
    log(f"  verdict: {(printability or {}).get('status')}")
    save()

    # 3. Repair (10 credits) when needed or requested.
    if prt.repair == "always" or (prt.repair == "auto" and needs_repair(printability)):
        log(f"Repairing mesh ({REPAIR_CREDITS} credits)")
        try:
            repair = client.run_task(PRINT_REPAIR, {"input_task_id": task_id}, on_progress=progress)
        except MeshyError as e:
            # Keep the already-paid-for model; the report will show it isn't clean.
            manifest["steps"]["repair"] = {"error": str(e)}
            log(f"  repair failed, continuing with unrepaired model: {e}")
        else:
            _record(manifest, "repair", repair)
            repaired_url = _glb_url(repair)
            model_path = client.download(repaired_url, out_dir / "repaired.glb")
            # Analyze's input_task_id doesn't list repair tasks, so re-check by URL.
            recheck = client.run_task(PRINT_ANALYZE, {"model_url": repaired_url}, on_progress=progress)
            manifest["steps"]["analyze_after_repair"] = {
                "task_id": recheck["id"],
                "printability": recheck.get("printability"),
            }
            log(f"  verdict after repair: {(recheck.get('printability') or {}).get('status')}")
        save()

    # 4. Local prep: orient, scale to mm, place on bed, export.
    log(f"Preparing for print: {prt.size_axis} = {prt.size_mm} mm")
    mesh = printprep.prepare(
        printprep.load_mesh(model_path), prt.size_mm, prt.size_axis, printprep.default_up_axis(model_path)
    )
    files = printprep.export(mesh, out_dir, "model", list(prt.formats))
    rep = printprep.report(mesh)
    manifest["preview"] = str(printprep.render_preview(mesh, out_dir / "preview.png"))
    manifest["print_files"] = [str(p) for p in files]
    manifest["mesh_report"] = rep.to_dict()
    manifest["output_dir"] = str(out_dir)
    save()

    # 5. Optional: split into separately printable parts (from the generation task).
    if prt.split:
        result = printing.run_split(
            client, task_id, prt.split, out_dir, prt.size_mm, prt.size_axis, log=log, on_progress=progress
        )
        manifest["steps"]["split"] = result
        manifest["credits_consumed"] += result.get("consumed_credits") or 0
        save()

    # 6. Optional: multi-color 3MF. Needs a textured model; repair strips textures, so this
    # branch always starts from the textured Meshy task, not the repaired mesh.
    if prt.multicolor:
        if kind == "text":
            log(f"Texturing for multi-color ({TEXTURE_CREDITS} credits)")
            refine: dict[str, Any] = {"mode": "refine", "preview_task_id": task_id}
            if prt.texture_prompt:
                refine["texture_prompt"] = prt.texture_prompt
            texture_task = client.run_task(TEXT_TO_3D, refine, on_progress=progress)
            _record(manifest, "texture", texture_task)
            textured_id = texture_task["id"]
        else:
            textured_id = task_id  # generated with should_texture=True
        save()
        result = printing.run_multicolor(
            client, {"input_task_id": textured_id}, prt.multicolor, out_dir,
            prt.size_mm, prt.size_axis, log=log, on_progress=progress,
        )
        manifest["steps"]["multicolor"] = result
        manifest["credits_consumed"] += result.get("consumed_credits") or 0
        save()
    return manifest


def prep_local(
    path: Path, prt: PrintOptions, up_axis: str | None = None, out_dir: Path | None = None, flip: bool = False
) -> dict:
    """Print-prep an existing local model file without calling Meshy."""
    out_dir = out_dir or path.parent
    mesh = printprep.prepare(
        printprep.load_mesh(path), prt.size_mm, prt.size_axis, up_axis or printprep.default_up_axis(path), flip
    )
    files = printprep.export(mesh, out_dir, f"{path.stem}-print", list(prt.formats))
    preview = printprep.render_preview(mesh, out_dir / f"{path.stem}-preview.png")
    return {
        "print_files": [str(p) for p in files],
        "preview": str(preview),
        "mesh_report": printprep.report(mesh).to_dict(),
    }


def _record(manifest: dict, step: str, task: dict, count: bool = True) -> None:
    manifest["steps"][step] = {
        "task_id": task["id"],
        "status": task.get("status"),
        "consumed_credits": task.get("consumed_credits"),
        "expires_at": task.get("expires_at"),
    }
    if count:
        manifest["credits_consumed"] += task.get("consumed_credits") or 0


def _glb_url(task: dict) -> str:
    url = (task.get("model_urls") or {}).get("glb")
    if not url:
        raise RuntimeError(f"Task {task.get('id')} returned no GLB URL: {task.get('model_urls')}")
    return url
