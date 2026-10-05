"""Meshy's 3D-printing post-processing: multi-color 3MF and auto split into parts.

Docs: https://docs.meshy.ai/api/multi-color-print and https://docs.meshy.ai/api/auto-split
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import trimesh

from . import printprep
from .client import PRINT_MULTICOLOR, PRINT_SPLIT, MeshyClient, log_stderr

# Credits per request, from https://docs.meshy.ai/api/pricing (checked 2026-10-05).
MULTICOLOR_CREDITS = 10
SPLIT_CREDITS = 10

MULTICOLOR_STYLES = ("realistic", "cartoon")
PRINTER_BRANDS = ("bambu", "anycubic", "creality", "elegoo", "flashforge", "prusa", "qidi", "snapmaker", "ankermake")
SPLIT_MODES = ("auto", "by_parts", "by_color")
CONNECTOR_TYPES = ("cube", "cylinder")
# Split only accepts Meshy 6/7 models; meshy-6-lite and meshy-t2 are rejected.
SPLIT_MODELS = ("latest", "meshy-7.1", "meshy-6")

Log = Callable[[str], None]


@dataclass
class MultiColorOptions:
    max_colors: int = 4
    style: str = "realistic"  # "cartoon" flattens into clean color regions
    printer_brand: str = "bambu"
    max_depth: int | None = None  # realistic only, 3-6

    def payload(self, source: dict[str, str]) -> dict[str, Any]:
        if not 1 <= self.max_colors <= 16:
            raise ValueError("max_colors must be 1-16")
        if self.style not in MULTICOLOR_STYLES:
            raise ValueError(f"style must be one of {MULTICOLOR_STYLES}")
        if self.printer_brand not in PRINTER_BRANDS:
            raise ValueError(f"printer_brand must be one of {PRINTER_BRANDS}")
        payload = {**source, "max_colors": self.max_colors, "style": self.style, "printer_brand": self.printer_brand}
        if self.max_depth is not None:
            if not 3 <= self.max_depth <= 6:
                raise ValueError("max_depth must be 3-6")
            payload["max_depth"] = self.max_depth
        return payload


@dataclass
class SplitOptions:
    mode: str = "auto"
    prompt: str | None = None  # names the parts, e.g. "head, torso, arms, base"
    connectors: bool = False
    connector_type: str | None = None
    connector_size: float | None = None  # 0.1-0.8, relative to the cut surface
    connector_height: float | None = None  # 0.1-0.8

    def payload(self, input_task_id: str) -> dict[str, Any]:
        if self.mode not in SPLIT_MODES:
            raise ValueError(f"split mode must be one of {SPLIT_MODES}")
        if self.mode != "auto" and not self.prompt:
            raise ValueError(f"split mode {self.mode} needs a prompt naming the parts")
        # Assembled layout keeps the source model's frame, so we can scale the parts to the
        # requested size and lay them out on the bed ourselves.
        payload: dict[str, Any] = {
            "input_task_id": input_task_id,
            "mode": self.mode,
            "layout": "assembled",
            "target_formats": ["glb"],
        }
        if self.mode != "auto":
            payload["prompt"] = self.prompt
        if self.connectors:
            payload["connectors"] = True
            if self.connector_type:
                if self.connector_type not in CONNECTOR_TYPES:
                    raise ValueError(f"connector_type must be one of {CONNECTOR_TYPES}")
                payload["connector_type"] = self.connector_type
            for key in ("connector_size", "connector_height"):
                value = getattr(self, key)
                if value is not None:
                    if not 0.1 <= value <= 0.8:
                        raise ValueError(f"{key} must be 0.1-0.8")
                    payload[key] = value
        return payload


def run_multicolor(
    client: MeshyClient,
    source: dict[str, str],
    opts: MultiColorOptions,
    out_dir: Path,
    size_mm: float | None = None,
    size_axis: str = "height",
    log: Log = log_stderr,
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    """Make a multi-color 3MF from a textured model. source is {"input_task_id": ...} or {"model_url": ...}.

    The 3MF is Meshy's own file with slicer presets inside, so it is not rescaled here.
    It is measured instead, and the slicer scale needed for the requested size is reported.
    """
    log(f"Creating multi-color 3MF ({MULTICOLOR_CREDITS} credits, up to {opts.max_colors} colors, {opts.style})")
    task = client.run_task(PRINT_MULTICOLOR, opts.payload(source), on_progress=on_progress)
    url = (task.get("model_urls") or {}).get("3mf")
    if not url:
        raise RuntimeError(f"Multi-color task {task.get('id')} returned no 3MF: {task.get('model_urls')}")
    path = client.download(url, out_dir / "multicolor.3mf")
    result: dict[str, Any] = {
        "task_id": task["id"],
        "consumed_credits": task.get("consumed_credits"),
        "file": str(path),
    }
    try:
        measured = printprep.measure(path)
    except Exception as e:  # noqa: BLE001 - Meshy's 3MF may use extensions trimesh can't read
        result["measure_error"] = str(e)
        return result
    result["measured"] = measured
    if size_mm:
        ext = measured["extents"]
        current = ext[2] if size_axis == "height" else max(ext)
        if current > 0:
            result["slicer_scale_percent"] = round(100 * size_mm / current, 1)
            result["scale_note"] = (
                "Assumes the 3MF is Z-up in mm (the 3MF default). Scale uniformly in the slicer and "
                "check the dimensions it shows."
            )
    try:
        preview = printprep.render_preview(printprep.load_mesh(path), out_dir / "multicolor-preview.png")
        result["preview"] = str(preview)
    except Exception as e:  # noqa: BLE001 - preview is best-effort
        result["preview_error"] = str(e)
    return result


def run_split(
    client: MeshyClient,
    input_task_id: str,
    opts: SplitOptions,
    out_dir: Path,
    size_mm: float,
    size_axis: str = "height",
    log: Log = log_stderr,
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    """Split a Meshy model into printable parts, then scale and lay them out locally."""
    log(f"Splitting into parts ({SPLIT_CREDITS} credits, mode {opts.mode})")
    task = client.run_task(PRINT_SPLIT, opts.payload(input_task_id), on_progress=on_progress)
    url = (task.get("model_urls") or {}).get("glb")
    if not url:
        raise RuntimeError(f"Split task {task.get('id')} returned no GLB: {task.get('model_urls')}")
    split_dir = out_dir / "parts"
    glb = client.download(url, split_dir / "split.glb")
    parts = printprep.prepare_parts(printprep.load_parts(glb), size_mm, size_axis, "y")
    files = printprep.export_parts(parts, split_dir)
    preview = printprep.render_preview(trimesh.util.concatenate([m for _, m in parts]), split_dir / "preview.png")
    return {
        "task_id": task["id"],
        "consumed_credits": task.get("consumed_credits"),
        "meshy_part_count": task.get("part_count"),
        "prompt_ignored": task.get("prompt_ignored", False),
        "parts": [
            {"file": str(p), "extents_mm": [round(float(x), 2) for x in m.extents]}
            for p, (_, m) in zip(files["stl"], parts)
        ],
        "parts_3mf": str(files["3mf"]),
        "preview": str(preview),
    }
