import base64
import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from meshy3d import pipeline, printprep
from meshy3d.cli import main
from meshy3d.client import MeshyClient, MeshyError

from .fakes import FakeMeshy, FakeResponse, box_glb


def make_client(fake, sleeps=None):
    sleeps = sleeps if sleeps is not None else []
    return MeshyClient("msy_test", session=fake, download_session=fake, sleep=sleeps.append)


# --- client ---------------------------------------------------------------

def test_client_sends_bearer_key_and_reads_balance():
    fake = FakeMeshy()
    assert make_client(fake).balance() == 1000
    assert fake.headers["Authorization"] == "Bearer msy_test"


def test_client_requires_key(monkeypatch):
    monkeypatch.delenv("MESHY_API_KEY", raising=False)
    with pytest.raises(MeshyError, match="MESHY_API_KEY"):
        MeshyClient()


def test_client_retries_429_using_retry_after():
    fake, sleeps = FakeMeshy(), []
    fake.queued = [FakeResponse(429, {"message": "slow down"}, {"Retry-After": "7"})]
    assert make_client(fake, sleeps).balance() == 1000
    assert sleeps == [7.0]


def test_client_raises_api_message_on_error():
    fake = FakeMeshy()
    fake.queued = [FakeResponse(402, {"message": "Insufficient credits"})]
    with pytest.raises(MeshyError, match="402: Insufficient credits") as e:
        make_client(fake).balance()
    assert e.value.status_code == 402


def test_wait_polls_with_retry_after_until_succeeded():
    fake, sleeps = FakeMeshy(polls_before_done=2), []
    client = make_client(fake, sleeps)
    task = client.run_task("/v2/text-to-3d", {"mode": "preview", "prompt": "cube"})
    assert task["status"] == "SUCCEEDED"
    assert sleeps == [3.0, 3.0]


def test_wait_raises_on_failed_task():
    fake = FakeMeshy(fail_endpoint="/v2/text-to-3d")
    with pytest.raises(MeshyError, match="FAILED: boom"):
        make_client(fake).run_task("/v2/text-to-3d", {"prompt": "cube"})


# --- printprep ------------------------------------------------------------

def test_prepare_converts_y_up_meters_to_z_up_mm_on_bed(tmp_path):
    path = tmp_path / "m.glb"
    path.write_bytes(box_glb((0.02, 0.05, 0.03)))  # 50 mm tall along Y
    mesh = printprep.prepare(printprep.load_mesh(path), 40, "height", "y")
    np.testing.assert_allclose(sorted(mesh.extents), [16, 24, 40], atol=1e-6)
    assert mesh.extents[2] == pytest.approx(40)
    assert mesh.bounds[0][2] == pytest.approx(0)
    np.testing.assert_allclose((mesh.bounds[0][:2] + mesh.bounds[1][:2]) / 2, [0, 0], atol=1e-9)


def test_prepare_longest_side():
    mesh = trimesh.creation.box(extents=[1, 4, 2])
    out = printprep.prepare(mesh, 100, "longest", "z")
    assert out.extents.max() == pytest.approx(100)
    assert out.extents[2] == pytest.approx(50)


@pytest.mark.parametrize("fmt", ["stl", "3mf"])
def test_export_round_trips_in_mm(tmp_path, fmt):
    mesh = printprep.prepare(trimesh.creation.box(extents=[1, 1, 2]), 30, "height", "z")
    (path,) = printprep.export(mesh, tmp_path, "model", [fmt])
    back = printprep.load_mesh(path)
    np.testing.assert_allclose(sorted(back.extents), [15, 15, 30], atol=1e-4)


def test_report_flags_open_mesh_and_multiple_bodies():
    a = trimesh.creation.box(extents=[10, 10, 10])
    b = trimesh.creation.box(extents=[10, 10, 10])
    b.apply_translation([50, 0, 0])
    rep = printprep.report(trimesh.util.concatenate([a, b]))
    assert rep.bodies == 2 and rep.is_watertight
    assert rep.volume_cm3 == pytest.approx(2.0)
    open_box = trimesh.creation.box(extents=[10, 10, 10])
    open_box.update_faces(np.arange(len(open_box.faces)) > 0)
    rep = printprep.report(open_box)
    assert not rep.is_watertight and rep.volume_cm3 is None


# --- pipeline -------------------------------------------------------------

def run_pipeline(tmp_path, fake, repair="auto", kind="text", source="a small vase"):
    return pipeline.run(
        make_client(fake), kind, source, pipeline.GenerateOptions(),
        pipeline.PrintOptions(size_mm=40, repair=repair), out_root=tmp_path, log=lambda _: None,
    )


def test_pipeline_healthy_model_skips_repair(tmp_path):
    fake = FakeMeshy(verdict="healthy")
    m = run_pipeline(tmp_path, fake)
    assert "repair" not in m["steps"]
    assert m["credits_consumed"] == 20
    assert not any("/print/repair" in c[1] for c in fake.calls)
    gen_post = next(c for c in fake.calls if c[0] == "POST")
    assert gen_post[2] == {"mode": "preview", "prompt": "a small vase", "ai_model": "latest"}
    assert m["mesh_report"]["extents_mm"][2] == pytest.approx(40)
    assert all(Path(f).exists() for f in m["print_files"] + [m["preview"]])
    saved = json.loads((Path(m["output_dir"]) / "manifest.json").read_text())
    assert saved["steps"]["analyze"]["printability"]["status"] == "healthy"


def test_pipeline_warning_does_not_trigger_repair(tmp_path):
    m = run_pipeline(tmp_path, FakeMeshy(verdict="warning"))
    assert "repair" not in m["steps"]


def test_pipeline_error_verdict_triggers_repair_and_recheck(tmp_path):
    fake = FakeMeshy(verdict="error")
    m = run_pipeline(tmp_path, fake)
    assert m["steps"]["repair"]["consumed_credits"] == 10
    assert m["credits_consumed"] == 30
    assert m["steps"]["analyze_after_repair"]["printability"]["status"] == "healthy"
    recheck_post = [c for c in fake.calls if c[0] == "POST" and c[1].endswith("/print/analyze")][-1]
    assert recheck_post[2]["model_url"].endswith("model.glb")
    assert m["print_files"][0].endswith("model.stl")


def test_pipeline_failed_repair_falls_back_to_raw_model(tmp_path):
    m = run_pipeline(tmp_path, FakeMeshy(verdict="error", fail_endpoint="/v1/print/repair"))
    assert "boom" in m["steps"]["repair"]["error"]
    assert m["credits_consumed"] == 20
    assert Path(m["print_files"][0]).exists()


def test_pipeline_repair_never(tmp_path):
    m = run_pipeline(tmp_path, FakeMeshy(verdict="error"), repair="never")
    assert "repair" not in m["steps"]


def test_pipeline_image_sends_untextured_data_uri(tmp_path):
    img = tmp_path / "photo.png"
    img.write_bytes(b"\x89PNGfake")
    fake = FakeMeshy()
    run_pipeline(tmp_path, fake, kind="image", source=str(img))
    post = next(c for c in fake.calls if c[0] == "POST")
    assert post[1].endswith("/v1/image-to-3d")
    assert post[2]["should_texture"] is False
    assert post[2]["image_url"] == "data:image/png;base64," + base64.b64encode(b"\x89PNGfake").decode()


def test_image_rejects_unsupported_format(tmp_path):
    img = tmp_path / "photo.webp"
    img.write_bytes(b"x")
    with pytest.raises(ValueError, match="png"):
        pipeline.image_to_url(str(img))


def test_meshy_t2_sets_smart_topology():
    p = pipeline.text_payload("cube", pipeline.GenerateOptions(ai_model="meshy-t2"))
    assert p["model_type"] == "smart-topology"


def test_estimate_credits():
    g = pipeline.GenerateOptions()
    assert pipeline.estimate_credits(g, "auto") == (20, 30)
    assert pipeline.estimate_credits(g, "never") == (20, 20)
    assert pipeline.estimate_credits(g, "always") == (30, 30)
    assert pipeline.estimate_credits(pipeline.GenerateOptions(ai_model="meshy-6-lite", geometry_resolution=None),
                                     "auto") == (5, 15)
    assert pipeline.estimate_credits(pipeline.GenerateOptions(geometry_resolution="2k"), "never") == (25, 25)
    assert pipeline.estimate_credits(g, "auto", include_generation=False) == (0, 10)


# --- cli ------------------------------------------------------------------

def test_cli_dry_run_makes_no_calls(capsys, monkeypatch):
    monkeypatch.delenv("MESHY_API_KEY", raising=False)
    assert main(["text", "a rook chess piece", "--height-mm", "50", "--model", "meshy-6-lite", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["request"]["ai_model"] == "meshy-6-lite"
    assert out["estimated_credits"] == [5, 15]


def test_cli_prep_local_file(tmp_path, capsys):
    src = tmp_path / "thing.glb"
    src.write_bytes(box_glb())
    assert main(["prep", str(src), "--longest-mm", "80", "--formats", "stl"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert max(out["mesh_report"]["extents_mm"]) == pytest.approx(80)
    assert (tmp_path / "thing-print.stl").exists()
