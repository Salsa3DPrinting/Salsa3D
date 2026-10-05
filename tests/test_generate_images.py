"""Reference-image generation (text-to-image / image-to-image) and handing images to 3D."""

import json
from pathlib import Path

import pytest

from meshy3d import images, pipeline
from meshy3d.cli import main

from .fakes import FakeMeshy
from .test_meshy3d import make_client

QUIET = {"log": lambda _: None}


@pytest.fixture
def photos(tmp_path):
    out = []
    for n in (1, 2):
        p = tmp_path / f"ref{n}.png"
        p.write_bytes(b"\x89PNGref" + bytes([n]))
        out.append(str(p))
    return out


def test_text_only_uses_text_to_image():
    endpoint, payload = images.generation_request("a red teapot, product photo", "nano-banana", pose_mode=None,
                                                  remove_background=True, aspect_ratio="4:3")
    assert endpoint == "/v1/text-to-image"
    assert payload == {"ai_model": "nano-banana", "prompt": "a red teapot, product photo",
                       "aspect_ratio": "4:3", "remove_background": True}


def test_references_switch_to_image_to_image(photos):
    endpoint, payload = images.generation_request("combine these", references=photos, multi_view=True)
    assert endpoint == "/v1/image-to-image"
    assert len(payload["reference_image_urls"]) == 2 and payload["generate_multi_view"] is True
    endpoint, payload = images.generation_request("restyle", image_task_id="t-9")
    assert endpoint == "/v1/image-to-image" and payload["input_task_id"] == "t-9"


@pytest.mark.parametrize("kwargs, match", [
    ({"multi_view": True, "aspect_ratio": "1:1"}, "multi-view"),
    ({"aspect_ratio": "3:2"}, "gpt-image"),
    ({"references": ["x"] * 6}, "at most 5"),
    ({"references": ["a.png"], "image_task_id": "t"}, "not both"),
    ({"references": ["a.png"], "pose_mode": "t-pose"}, "pose_mode"),
    ({"pose_mode": "x-pose"}, "pose_mode"),
    ({"ai_model": "dall-e"}, "ai_model"),
])
def test_generation_request_rejects_documented_conflicts(kwargs, match):
    with pytest.raises(ValueError, match=match):
        images.generation_request("prompt", **kwargs)


def test_estimates_use_endpoint_prices_and_multi_view_range():
    assert images.estimate_generation("/v1/text-to-image", "gpt-image-2", False) == (9, 9)
    assert images.estimate_generation("/v1/image-to-image", "gpt-image-2", False) == (12, 12)
    assert images.estimate_generation("/v1/text-to-image", "nano-banana-2", True, count=2) == (12, 36)


def test_generate_images_multi_view_saves_three_views_per_variant(tmp_path):
    fake = FakeMeshy()
    m = images.generate_images(make_client(fake), "a chunky robot toy", multi_view=True, count=2,
                               out_root=tmp_path, **QUIET)
    assert len(fake.posts("/v1/text-to-image")) == 2
    names = [Path(o).name for t in m["tasks"] for o in t["outputs"]]
    assert names == ["gen-1-view1.png", "gen-1-view2.png", "gen-1-view3.png",
                     "gen-2-view1.png", "gen-2-view2.png", "gen-2-view3.png"]
    assert all(Path(Path(m["output_dir"]) / n).exists() for n in names)
    saved = json.loads((Path(m["output_dir"]) / "manifest.json").read_text())
    assert saved["estimated_credits"] == [12, 36] and saved["tasks"][1]["task_id"] == "task-2"


def test_image_task_feeds_3d_without_downloading(tmp_path):
    fake = FakeMeshy()
    m = pipeline.run(make_client(fake), "multi-image", pipeline.image_task_source("img-task-1"),
                     pipeline.GenerateOptions(), pipeline.PrintOptions(size_mm=60), out_root=tmp_path, **QUIET)
    (post,) = fake.posts("/v1/multi-image-to-3d")
    assert post == {"input_task_id": "img-task-1", "ai_model": "latest", "should_texture": False}
    assert "from-image-task-img-task" in m["output_dir"]
    with pytest.raises(ValueError, match="image or multi-image"):
        pipeline.generate_payload("text", pipeline.image_task_source("x"), pipeline.GenerateOptions(), False)


def test_cli_generate_and_from_image_task_dry_runs(capsys, photos):
    assert main(["generate-image", "same object, three views", "--ref", photos[0], "--ref", photos[1],
                 "--multi-view", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["endpoint"] == "/v1/image-to-image" and out["estimated_credits"] == [6, 18]
    assert all(u.endswith("(truncated)") for u in out["request"]["reference_image_urls"])
    assert main(["image", "--from-image-task", "t-1", "--height-mm", "50", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["request"]["input_task_id"] == "t-1"
    assert main(["image", photos[0], "--from-image-task", "t-1", "--height-mm", "50", "--dry-run"]) == 2
    assert "not both" in capsys.readouterr().err
    assert main(["multi-image", "--height-mm", "50", "--dry-run"]) == 2
