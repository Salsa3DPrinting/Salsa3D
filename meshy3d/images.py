"""Meshy 2D image generation: edit photos, or generate reference images for 3D.

- edit_images: one image-to-image task per photo (e.g. remove hand/background).
- generate_images: text-to-image, or image-to-image from up to 5 reference photos / an earlier
  image task, optionally as a 3-view sheet (generate_multi_view) for multi-image to 3D.

Docs: https://docs.meshy.ai/api/text-to-image and https://docs.meshy.ai/api/image-to-image
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .client import IMAGE_TO_IMAGE, TEXT_TO_IMAGE, MeshyClient, log_stderr
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
# Text-to-image prices differ for the GPT models (https://docs.meshy.ai/api/text-to-image, 2026-10-05).
TEXT_MODEL_CREDITS = {**EDIT_MODEL_CREDITS, "gpt-image-2": 9, "gpt-image-2-5-flare": 9, "gpt-image-2-5-sunburst": 9}
MAX_REFERENCES = 5
MULTI_VIEW_IMAGES = 3  # docs: a multi-view task returns three images
POSE_MODES = ("a-pose", "t-pose")
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


def _check_aspect(aspect_ratio: str | None, ai_model: str, multi_view: bool) -> None:
    if not aspect_ratio:
        return
    if multi_view:
        raise ValueError("aspect_ratio can't be combined with multi-view (Meshy rejects it)")
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValueError(f"aspect_ratio must be one of {ASPECT_RATIOS}")
    if aspect_ratio in GPT_ONLY_RATIOS and not ai_model.startswith("gpt-"):
        raise ValueError(f"aspect_ratio {aspect_ratio} is only available on gpt-image models")


def generation_request(
    prompt: str,
    ai_model: str = "nano-banana-2",
    references: list[str] | None = None,
    image_task_id: str | None = None,
    multi_view: bool = False,
    aspect_ratio: str | None = None,
    remove_background: bool = False,
    pose_mode: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return (endpoint, payload). With references or image_task_id it's image-to-image, else text-to-image."""
    if not prompt or not prompt.strip():
        raise ValueError("a prompt is required")
    references = references or []
    if references and image_task_id:
        raise ValueError("use reference images or an image task id, not both")
    edit = bool(references or image_task_id)
    prices = EDIT_MODEL_CREDITS if edit else TEXT_MODEL_CREDITS
    if ai_model not in prices:
        raise ValueError(f"ai_model must be one of {list(prices)}")
    _check_aspect(aspect_ratio, ai_model, multi_view)
    payload: dict[str, Any] = {"ai_model": ai_model, "prompt": prompt}
    if edit:
        if pose_mode:
            raise ValueError("pose_mode is only available for text-to-image")
        if image_task_id:
            payload["input_task_id"] = image_task_id
        else:
            if len(references) > MAX_REFERENCES:
                raise ValueError(f"at most {MAX_REFERENCES} reference images")
            payload["reference_image_urls"] = [image_to_url(r) for r in references]
    elif pose_mode:
        if pose_mode not in POSE_MODES:
            raise ValueError(f"pose_mode must be one of {POSE_MODES}")
        payload["pose_mode"] = pose_mode
    if multi_view:
        payload["generate_multi_view"] = True
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if remove_background:
        payload["remove_background"] = True
    return (IMAGE_TO_IMAGE if edit else TEXT_TO_IMAGE), payload


def estimate_generation(endpoint: str, ai_model: str, multi_view: bool, count: int = 1) -> tuple[int, int]:
    """(low, high) credits. Meshy prices per image but doesn't document how a 3-view task is billed,
    so multi-view is estimated as anywhere from one image to three."""
    price = (EDIT_MODEL_CREDITS if endpoint == IMAGE_TO_IMAGE else TEXT_MODEL_CREDITS)[ai_model]
    return count * price, count * price * (MULTI_VIEW_IMAGES if multi_view else 1)


def generate_images(
    client: MeshyClient,
    prompt: str,
    ai_model: str = "nano-banana-2",
    references: list[str] | None = None,
    image_task_id: str | None = None,
    multi_view: bool = False,
    aspect_ratio: str | None = None,
    remove_background: bool = False,
    pose_mode: str | None = None,
    count: int = 1,
    out_root: Path = Path("output"),
    log: Callable[[str], None] = log_stderr,
) -> dict:
    """Run `count` independent generations (variants to choose from); saves gen-T[-V].png for review."""
    if not 1 <= count <= 8:
        raise ValueError("count must be 1-8")
    endpoint, payload = generation_request(prompt, ai_model, references, image_task_id, multi_view,
                                           aspect_ratio, remove_background, pose_mode)
    label = Path(references[0]).stem if references else (image_task_id or prompt)[:30]
    out_dir = new_out_dir(out_root, f"gen-{label}")
    low, high = estimate_generation(endpoint, ai_model, multi_view, count)
    manifest: dict[str, Any] = {
        "kind": "image-generate",
        "endpoint": endpoint,
        "request": {k: v for k, v in payload.items() if k != "reference_image_urls"},
        "references": references or [],
        "tasks": [],
        "credits_consumed": 0,
        "estimated_credits": [low, high],
        "output_dir": str(out_dir),
    }
    for t in range(1, count + 1):
        log(f"Generating image {t}/{count} with {ai_model} ({'multi-view' if multi_view else 'single'})")
        task = client.run_task(endpoint, payload)
        urls = task.get("image_urls") or []
        outputs = [str(client.download(u, out_dir / f"gen-{t}{f'-view{v}' if len(urls) > 1 else ''}.png"))
                   for v, u in enumerate(urls, 1)]
        manifest["tasks"].append({"task_id": task["id"], "outputs": outputs,
                                  "consumed_credits": task.get("consumed_credits")})
        manifest["credits_consumed"] += task.get("consumed_credits") or 0
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


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
