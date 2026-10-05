"""Meshy image editing (image-to-image), e.g. to clean up photos before 3D generation.

Docs: https://docs.meshy.ai/api/image-to-image
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .client import IMAGE_TO_IMAGE, MeshyClient, log_stderr
from .pipeline import image_to_url, new_out_dir

# Credits per output image, from https://docs.meshy.ai/api/image-to-image (checked 2026-10-05).
EDIT_MODEL_CREDITS = {
    "nano-banana": 3,
    "nano-banana-2": 6,
    "nano-banana-pro": 9,
    "gpt-image-2": 12,
    "gpt-image-2-5-flare": 12,
    "gpt-image-2-5-sunburst": 12,
}
ASPECT_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3")
GPT_ONLY_RATIOS = ("3:2", "2:3")

CLEANUP_PROMPT = (
    "Edit this photo into a clean product photo of the same object. Remove the hand and fingers completely "
    "and reconstruct any part of the object they covered so it matches the rest of the object. Remove the "
    "background and place the object alone on a plain pure white background with soft, even lighting. "
    "Keep the object exactly as it is: same shape, proportions, colors, parts, details and text, and the "
    "same camera angle. Do not add, remove or restyle anything on the object."
)


def edit_payload(image: str, prompt: str, ai_model: str, aspect_ratio: str | None) -> dict[str, Any]:
    if ai_model not in EDIT_MODEL_CREDITS:
        raise ValueError(f"ai_model must be one of {list(EDIT_MODEL_CREDITS)}")
    payload: dict[str, Any] = {
        "ai_model": ai_model,
        "prompt": prompt,
        "reference_image_urls": [image_to_url(image)],
    }
    if aspect_ratio:
        if aspect_ratio not in ASPECT_RATIOS:
            raise ValueError(f"aspect_ratio must be one of {ASPECT_RATIOS}")
        if aspect_ratio in GPT_ONLY_RATIOS and not ai_model.startswith("gpt-"):
            raise ValueError(f"aspect_ratio {aspect_ratio} is only available on gpt-image models")
        payload["aspect_ratio"] = aspect_ratio
    return payload


def estimate_credits(n_images: int, ai_model: str) -> int:
    return n_images * EDIT_MODEL_CREDITS[ai_model]


def edit_images(
    client: MeshyClient,
    images: list[str],
    prompt: str,
    ai_model: str = "nano-banana-2",
    aspect_ratio: str | None = None,
    out_root: Path = Path("output"),
    log: Callable[[str], None] = log_stderr,
) -> dict:
    """Edit each image separately with the same prompt; saves edited-N.png for review."""
    payloads = [edit_payload(i, prompt, ai_model, aspect_ratio) for i in images]  # validate all first
    out_dir = new_out_dir(out_root, f"edit-{Path(images[0]).stem}")
    manifest: dict[str, Any] = {"kind": "image-edit", "prompt": prompt, "ai_model": ai_model,
                                "aspect_ratio": aspect_ratio, "images": [], "credits_consumed": 0,
                                "estimated_credits": estimate_credits(len(images), ai_model),
                                "output_dir": str(out_dir)}
    for n, (image, payload) in enumerate(zip(images, payloads), 1):
        log(f"Editing {image} with {ai_model} ({EDIT_MODEL_CREDITS[ai_model]} credits)")
        task = client.run_task(IMAGE_TO_IMAGE, payload)
        outputs = [
            str(client.download(url, out_dir / f"edited-{n}{'' if i == 1 else f'-{i}'}.png"))
            for i, url in enumerate(task.get("image_urls") or [], 1)
        ]
        manifest["images"].append({"source": image, "task_id": task["id"], "outputs": outputs,
                                   "consumed_credits": task.get("consumed_credits")})
        # Meshy's documented image-to-image response has no consumed_credits; count only what it reports.
        manifest["credits_consumed"] += task.get("consumed_credits") or 0
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
