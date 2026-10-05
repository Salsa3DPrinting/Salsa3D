"""Multi-color 3MF, auto split, and Creative Lab presets."""

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from meshy3d import pipeline, presets, printing, printprep
from meshy3d.cli import main

from .fakes import FakeMeshy, box_glb, two_part_glb
from .test_meshy3d import make_client

QUIET = {"log": lambda _: None}


# --- printprep additions ----------------------------------------------------

def test_orient_flat_puts_thinnest_side_down():
    badge = trimesh.creation.box(extents=[40, 3, 30])  # thin along Y
    out = printprep.prepare(badge, 50, "longest", "flat")
    assert out.extents[2] == pytest.approx(50 * 3 / 40)
    assert out.extents.max() == pytest.approx(50)
    assert out.bounds[0][2] == pytest.approx(0)


def test_flip_turns_model_upside_down_and_keeps_it_on_bed():
    cone = trimesh.creation.cone(radius=10, height=30)  # apex up (+Z)
    flipped = printprep.prepare(cone, None, up_axis="z", flip=True)
    radius = np.linalg.norm(flipped.vertices[:, :2] - flipped.vertices[:, :2].mean(axis=0), axis=1)
    rim = flipped.vertices[radius > 9.9]
    np.testing.assert_allclose(rim[:, 2], 30, atol=1e-6)  # wide base is now on top
    assert flipped.bounds[0][2] == pytest.approx(0)


def test_prepare_without_size_keeps_units():
    out = printprep.prepare(trimesh.creation.box(extents=[18, 18, 9]), None, up_axis="z")
    np.testing.assert_allclose(out.extents, [18, 18, 9])


def test_prepare_parts_scales_assembly_and_lays_parts_in_a_row(tmp_path):
    path = tmp_path / "split.glb"
    path.write_bytes(two_part_glb())  # assembled height 0.05 m along Y
    parts = printprep.prepare_parts(printprep.load_parts(path), 100, "height", "y")
    assert len(parts) == 2
    heights = sorted(round(m.extents[2], 3) for _, m in parts)
    assert heights == [40.0, 60.0]  # 0.02 and 0.03 m scaled by 100/0.05 = 2000
    for _, m in parts:
        assert m.bounds[0][2] == pytest.approx(0)
    (_, a), (_, b) = parts
    assert b.bounds[0][0] >= a.bounds[1][0] + 4.99  # no overlap, 5 mm gap

    files = printprep.export_parts(parts, tmp_path / "out")
    assert len(files["stl"]) == 2 and all(p.exists() for p in files["stl"])
    assert printprep.measure(files["3mf"])["objects"] == 2


# --- option validation ------------------------------------------------------

def test_multicolor_options_validate():
    assert printing.MultiColorOptions().payload({"input_task_id": "t"}) == {
        "input_task_id": "t", "max_colors": 4, "style": "realistic", "printer_brand": "bambu"}
    for bad in ({"max_colors": 17}, {"style": "neon"}, {"printer_brand": "acme"}, {"max_depth": 2}):
        with pytest.raises(ValueError):
            printing.MultiColorOptions(**bad).payload({})


def test_split_options_validate():
    p = printing.SplitOptions().payload("t")
    assert p == {"input_task_id": "t", "mode": "auto", "layout": "assembled", "target_formats": ["glb"]}
    with pytest.raises(ValueError, match="prompt"):
        printing.SplitOptions(mode="by_parts").payload("t")
    with pytest.raises(ValueError, match="0.1-0.8"):
        printing.SplitOptions(connectors=True, connector_size=0.9).payload("t")
    p = printing.SplitOptions("by_parts", "head, body", True, "cylinder", 0.4, 0.2).payload("t")
    assert p["prompt"] == "head, body" and p["connector_type"] == "cylinder" and p["connector_height"] == 0.2


def test_validate_rejects_documented_unsupported_combinations():
    prt = pipeline.PrintOptions(size_mm=40, split=printing.SplitOptions())
    with pytest.raises(ValueError, match="ai_model"):
        pipeline.validate("text", pipeline.GenerateOptions(ai_model="meshy-6-lite"), prt)
    prt = pipeline.PrintOptions(size_mm=40, split=printing.SplitOptions("by_color", "red, blue"))
    with pytest.raises(ValueError, match="image"):
        pipeline.validate("text", pipeline.GenerateOptions(), prt)
    with pytest.raises(ValueError, match="texture_prompt"):
        pipeline.validate("text", pipeline.GenerateOptions(), pipeline.PrintOptions(size_mm=40, texture_prompt="x"))


def test_estimate_includes_texture_multicolor_and_split():
    prt = pipeline.PrintOptions(size_mm=40, multicolor=printing.MultiColorOptions(), split=printing.SplitOptions())
    assert pipeline.estimate_credits(pipeline.GenerateOptions(), "auto", prt=prt) == (50, 60)
    assert pipeline.estimate_credits(pipeline.GenerateOptions(), "never", include_generation=False, prt=prt) == (20, 20)


# --- pipeline with multi-color / split -------------------------------------

def _run(tmp_path, fake, kind="text", source="a fox", **prt_kwargs):
    prt = pipeline.PrintOptions(size_mm=40, **prt_kwargs)
    return pipeline.run(make_client(fake), kind, source, pipeline.GenerateOptions(), prt, out_root=tmp_path, **QUIET)


def test_text_multicolor_textures_then_converts_the_textured_task(tmp_path):
    fake = FakeMeshy()
    m = _run(tmp_path, fake, multicolor=printing.MultiColorOptions(max_colors=6, style="cartoon"),
             texture_prompt="orange fur")
    refine = [p for p in fake.posts("/v2/text-to-3d") if p.get("mode") == "refine"]
    assert refine == [{"mode": "refine", "preview_task_id": "task-1", "texture_prompt": "orange fur"}]
    texture_id = m["steps"]["texture"]["task_id"]
    (mc,) = fake.posts("/v1/print/multi-color")
    assert mc["input_task_id"] == texture_id and mc["max_colors"] == 6 and mc["style"] == "cartoon"
    result = m["steps"]["multicolor"]
    assert Path(result["file"]).exists()
    assert result["measured"]["objects"] == 2
    assert result["slicer_scale_percent"] == pytest.approx(round(100 * 40 / 30, 1))
    assert m["credits_consumed"] == 20 + 10 + 10
    assert Path(m["print_files"][0]).exists()  # single-color STL is still produced


def test_image_multicolor_generates_textured_and_uses_generation_task(tmp_path):
    img = tmp_path / "cat.jpg"
    img.write_bytes(b"\xff\xd8fake")
    fake = FakeMeshy()
    m = _run(tmp_path, fake, kind="image", source=str(img), multicolor=printing.MultiColorOptions())
    (gen,) = fake.posts("/v1/image-to-3d")
    assert gen["should_texture"] is True
    assert fake.posts("/v1/print/multi-color")[0]["input_task_id"] == m["steps"]["generate"]["task_id"]
    assert "texture" not in m["steps"]


def test_split_produces_scaled_parts(tmp_path):
    fake = FakeMeshy()
    m = _run(tmp_path, fake, split=printing.SplitOptions("by_parts", "head, body", connectors=True))
    (sp,) = fake.posts("/v1/print/split")
    assert sp["input_task_id"] == "task-1" and sp["layout"] == "assembled" and sp["connectors"] is True
    split = m["steps"]["split"]
    assert split["meshy_part_count"] == 2
    assert all(Path(p["file"]).exists() for p in split["parts"])
    heights = sorted(p["extents_mm"][2] for p in split["parts"])
    assert sum(heights) == pytest.approx(40, abs=0.01)  # assembled height = requested 40 mm
    assert m["credits_consumed"] == 30


# --- Creative Lab presets ---------------------------------------------------

@pytest.fixture
def photo(tmp_path):
    img = tmp_path / "dog.webp"
    img.write_bytes(b"RIFFfakeWEBP")
    return img


def test_prototype_saves_concepts_and_manifest(tmp_path, photo):
    fake = FakeMeshy()
    m = presets.run_prototype(make_client(fake), presets.get("keychain"), str(photo), {"name_text": "Rex"},
                              tmp_path, **QUIET)
    (post,) = fake.posts("/creative-lab/keychain/v1/prototype")
    assert post["name_text"] == "Rex" and post["image_url"].startswith("data:image/webp;base64,")
    out = Path(m["output_dir"])
    assert (out / "concept-1.png").exists()
    assert json.loads((out / "manifest.json").read_text())["steps"]["prototype"]["task_id"] == "task-1"


def test_keychain_build_from_dir_lays_relief_flat_at_size(tmp_path, photo):
    fake = FakeMeshy(glb=box_glb((0.04, 0.035, 0.004)))  # thin badge
    client = make_client(fake)
    preset = presets.get("keychain")
    m = presets.run_prototype(client, preset, str(photo), {}, tmp_path, **QUIET)
    out = Path(m["output_dir"])
    m = presets.run_build(client, preset, out, options={"size_mm": 50, "badge_shape": "hexagon"}, fmt="glb", **QUIET)
    (body,) = fake.posts("/creative-lab/keychain/v1/build")
    assert body == {"input_task_id": "task-1", "options": {"size_mm": 50, "badge_shape": "hexagon"},
                    "output": {"format": "glb"}}
    rep = m["steps"]["build"]["print"]["mesh_report"]
    assert max(rep["extents_mm"]) == pytest.approx(50)
    assert rep["extents_mm"][2] == pytest.approx(5.0)  # 0.004/0.04 * 50: thin side is Z
    assert m["credits_consumed"] == 36


def test_figure_build_requires_size_and_supports_multicolor(tmp_path):
    preset = presets.get("figure")
    with pytest.raises(ValueError, match="height-mm"):
        presets.run_build(make_client(FakeMeshy()), preset, tmp_path, prototype_id="p", **QUIET)
    fake = FakeMeshy()
    m = presets.run_build(make_client(fake), preset, tmp_path, prototype_id="p", size_mm=80,
                          multicolor=printing.MultiColorOptions(style="cartoon"), **QUIET)
    assert fake.posts("/creative-lab/figure/v1/build") == [{"input_task_id": "p"}]
    assert m["steps"]["build"]["print"]["mesh_report"]["extents_mm"][2] == pytest.approx(80)
    (mc,) = fake.posts("/v1/print/multi-color")
    assert mc["model_url"].split("?")[0].endswith("/model.glb")
    assert m["credits_consumed"] == 40


def test_keycap_build_uses_first_candidate_and_converts_meters(tmp_path, photo):
    fake = FakeMeshy(glb=box_glb((0.018, 0.012, 0.018)))
    client = make_client(fake)
    preset = presets.get("keycap")
    m = presets.run_prototype(client, preset, str(photo), {}, tmp_path, **QUIET)
    m = presets.run_build(client, preset, Path(m["output_dir"]), **QUIET)
    assert fake.posts("/creative-lab/keycap/v1/build")[0]["candidate_id"] == "cand-1"
    pr = m["steps"]["build"]["print"]
    assert sorted(pr["mesh_report"]["extents_mm"]) == pytest.approx([12, 18, 18])
    assert "meters" in pr["notes"][0]


def test_lamp_build_keeps_meshy_stls_as_is(tmp_path):
    fake = FakeMeshy()
    m = presets.run_build(make_client(fake), presets.get("lamp"), tmp_path, prototype_id="p",
                          options={"diameter_mm": 120}, **QUIET)
    pr = m["steps"]["build"]["print"]
    assert set(pr["measured"]) == {"lamp_stl", "base_stl"}
    assert pr["measured"]["lamp_stl"]["extents"] == [100, 100, 120]
    assert Path(pr["measured"]["lamp_stl"]["preview"]).exists()
    assert (tmp_path / "lamp_stl.stl").exists()


def test_fidget_pixel_prototype_requires_type(photo):
    with pytest.raises(ValueError, match="type"):
        presets.prototype_payload(presets.get("fidget-pixel"), str(photo), {})


def test_single_stage_collapsible(tmp_path, photo):
    fake = FakeMeshy()
    m = presets.run_single(make_client(fake), presets.get("fidget-collapsible"), str(photo), tmp_path, **QUIET)
    assert fake.posts("/creative-lab/fidget-collapsible/v1")[0]["image_url"].startswith("data:image/webp")
    assert m["credits_consumed"] == 30  # fake charges 30 per build; real price is 6
    assert m["steps"]["build"]["print"]["measured"]["stl"]["extents"] == [100, 100, 120]


def test_build_rejects_options_a_preset_does_not_take():
    with pytest.raises(ValueError, match="no options"):
        presets.build_payload(presets.get("figure"), "p", {"size_mm": 10}, None, None)
    with pytest.raises(ValueError, match="output format"):
        presets.build_payload(presets.get("keycap"), "p", {}, "zip", "c")


def test_image_to_3d_still_rejects_webp(photo):
    with pytest.raises(ValueError, match="png"):
        pipeline.image_to_url(str(photo))


# --- CLI --------------------------------------------------------------------

def test_cli_preset_list(capsys):
    assert main(["preset", "list"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["keycap"]["credits"] == {"prototype": 12, "build": 50}
    assert out["fidget-collapsible"]["stages"] == "single"


def test_cli_preset_prototype_dry_run_parses_params(capsys, photo):
    assert main(["preset", "prototype", "fidget-pixel", str(photo), "--param", "type=person", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["request"]["type"] == "person" and out["request"]["image_url"].endswith("(truncated)")


def test_cli_build_dry_run_parses_typed_options(capsys):
    assert main(["preset", "build", "fridge-magnet", "--prototype-task", "p", "--option", "size_mm=75",
                 "--option", "has_closed_back=false", "--option", "badge_shape=star", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["request"]["options"] == {"size_mm": 75, "has_closed_back": False, "badge_shape": "star"}


def test_cli_text_dry_run_with_multicolor_and_split(capsys):
    assert main(["text", "a robot", "--height-mm", "60", "--multicolor", "--colors", "5",
                 "--split", "--split-mode", "by_parts", "--split-prompt", "head, body", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["estimated_credits"] == [50, 60]
    assert out["multicolor"]["max_colors"] == 5 and out["split"]["prompt"] == "head, body"


def test_cli_reports_invalid_combination_without_traceback(capsys):
    assert main(["text", "a robot", "--height-mm", "60", "--split", "--model", "meshy-t2", "--dry-run"]) == 2
    assert "ai_model" in capsys.readouterr().err


def test_cli_prototype_then_build_from_dir(tmp_path, photo, monkeypatch, capsys):
    fake = FakeMeshy(glb=box_glb((0.06, 0.05, 0.005)))
    monkeypatch.setattr("meshy3d.cli.MeshyClient", lambda: make_client(fake))
    assert main(["preset", "prototype", "fridge-magnet", str(photo), "--out", str(tmp_path)]) == 0
    out_dir = json.loads(capsys.readouterr().out)["output_dir"]
    assert main(["preset", "build", "fridge-magnet", "--dir", out_dir, "--option", "size_mm=70"]) == 0
    m = json.loads(capsys.readouterr().out)
    assert fake.posts("/creative-lab/fridge-magnet/v1/build")[0]["input_task_id"] == "task-1"
    assert max(m["steps"]["build"]["print"]["mesh_report"]["extents_mm"]) == pytest.approx(70)
    assert m["credits_consumed"] == 36


def test_preset_multicolor_combination_rejected_before_build(tmp_path):
    fake = FakeMeshy()
    for name, fmt in (("lamp", None), ("keychain", "obj")):
        with pytest.raises(ValueError, match="multi-color|Multi-color"):
            presets.run_build(make_client(fake), presets.get(name), tmp_path, prototype_id="p", fmt=fmt,
                              multicolor=printing.MultiColorOptions(), **QUIET)
    assert fake.posts("/build") == []  # nothing was charged
