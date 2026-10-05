"""Photo cleanup (image-to-image) and multi-image to 3D."""

import json
from pathlib import Path

import pytest

from meshy3d import images, pipeline, printing
from meshy3d.cli import main

from .fakes import FakeMeshy
from .test_meshy3d import make_client

QUIET = {"log": lambda _: None}


@pytest.fixture
def photos(tmp_path):
    paths = []
    for n in (1, 2, 3):
        p = tmp_path / f"{n}.jpg"
        p.write_bytes(b"\xff\xd8photo" + bytes([n]))
        paths.append(str(p))
    return paths


def test_edit_images_one_task_per_photo(tmp_path, photos):
    fake = FakeMeshy()
    m = images.edit_images(make_client(fake), photos, "remove the hand", "nano-banana-2", "3:4", tmp_path, **QUIET)
    posts = fake.posts("/v1/image-to-image")
    assert len(posts) == 3
    assert posts[0]["ai_model"] == "nano-banana-2" and posts[0]["aspect_ratio"] == "3:4"
    assert posts[0]["prompt"] == "remove the hand"
    assert [len(p["reference_image_urls"]) for p in posts] == [1, 1, 1]
    assert posts[1]["reference_image_urls"][0].startswith("data:image/jpeg;base64,")
    outs = [o for img in m["images"] for o in img["outputs"]]
    assert [Path(o).name for o in outs] == ["edited-1.png", "edited-2.png", "edited-3.png"]
    assert all(Path(o).exists() for o in outs)
    assert m["estimated_credits"] == 18
    assert m["credits_consumed"] == 0  # Meshy didn't report any; we don't invent a number
    assert json.loads((Path(m["output_dir"]) / "manifest.json").read_text())["images"][2]["task_id"] == "task-3"


def test_edit_validates_before_spending(photos):
    with pytest.raises(ValueError, match="gpt-image"):
        images.edit_payload(photos[0], "x", "nano-banana-2", "3:2")
    with pytest.raises(ValueError, match="ai_model"):
        images.edit_payload(photos[0], "x", "dall-e", None)


def test_multi_image_pipeline_textured_for_multicolor(tmp_path, photos):
    fake = FakeMeshy()
    prt = pipeline.PrintOptions(size_mm=203.2, multicolor=printing.MultiColorOptions())
    m = pipeline.run(make_client(fake), "multi-image", photos, pipeline.GenerateOptions(), prt,
                     out_root=tmp_path, **QUIET)
    (gen,) = fake.posts("/v1/multi-image-to-3d")
    assert len(gen["image_urls"]) == 3 and gen["should_texture"] is True
    assert fake.posts("/v1/print/multi-color")[0]["input_task_id"] == m["steps"]["generate"]["task_id"]
    assert m["mesh_report"]["extents_mm"][2] == pytest.approx(203.2)
    assert m["credits_consumed"] == 30


def test_multi_image_validation(photos):
    with pytest.raises(ValueError, match="1 to 4"):
        pipeline.multi_image_payload(photos * 2, pipeline.GenerateOptions())
    prt = pipeline.PrintOptions(size_mm=50)
    with pytest.raises(ValueError, match="meshy-t2"):
        pipeline.validate("multi-image", pipeline.GenerateOptions(ai_model="meshy-t2"), prt)
    split = pipeline.PrintOptions(size_mm=50, split=printing.SplitOptions("by_color", "red, gray"))
    pipeline.validate("multi-image", pipeline.GenerateOptions(), split)  # by_color allowed for photos


def test_cli_dry_runs(capsys, photos):
    assert main(["edit-image", *photos, "--extra", "It is a model isolator.", "--aspect", "3:4", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["estimated_credits"] == 18 and out["requests"][0]["prompt"].endswith("It is a model isolator.")
    assert main(["multi-image", *photos, "--height-mm", "203.2", "--multicolor", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["estimated_credits"] == [40, 50]
    assert all(u.endswith("(truncated)") for u in out["request"]["image_urls"])
