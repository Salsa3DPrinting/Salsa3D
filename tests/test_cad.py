"""Bambu multi-part 3MF writer and the parametric isolator model."""

import json
import zipfile

import numpy as np
import pytest
import trimesh

from meshy3d import bambu3mf


def test_bambu3mf_round_trip(tmp_path):
    a = trimesh.creation.box(extents=[20, 10, 30])
    b = trimesh.creation.box(extents=[4, 4, 4])
    b.apply_translation([0, -7, 10])  # touches a's front face
    path = bambu3mf.write([bambu3mf.Part("body", a, 1), bambu3mf.Part("button", b, 3)],
                          ["#222222", "#FFFFFF", "#FF0000"], tmp_path / "m.3mf", name="demo")
    parts = bambu3mf.read_parts(path)
    assert [(p["name"], p["filament"]) for p in parts] == [("body", 1), ("button", 3)]
    assert all(p["mesh"].is_watertight for p in parts)
    allv = np.vstack([p["mesh"].vertices for p in parts])
    assert allv[:, 2].min() == pytest.approx(0)  # placed on the bed
    np.testing.assert_allclose(allv.max(axis=0) - allv.min(axis=0), [20, 14, 30], atol=1e-4)  # button spans y -9..-5
    with zipfile.ZipFile(path) as z:
        settings = json.loads(z.read("Metadata/project_settings.config"))
        root = z.read("3D/3dmodel.model").decode()
    assert settings["filament_colour"] == ["#222222FF", "#FFFFFFFF", "#FF0000FF"]
    assert root.count("<component ") == 2
    # Standard 3MF readers see the geometry too.
    assert trimesh.load(path).extents[2] == pytest.approx(30)


def test_bambu3mf_rejects_bad_filament(tmp_path):
    with pytest.raises(ValueError, match="filament 4"):
        bambu3mf.write([bambu3mf.Part("x", trimesh.creation.box(), 4)], ["#000000"], tmp_path / "x.3mf")


def test_isolator_builds_clean():
    from cad import isolator

    parts = isolator.build()
    report = isolator.check(parts)
    assert report["overlaps_mm3"] == {}
    assert all(p["watertight"] for p in report["parts"].values())
    assert report["extents_mm"][2] == pytest.approx(isolator.HEIGHT)
    assert {p.filament for p in parts} == set(range(1, 9))
    combined = isolator.union([p.mesh for p in parts])
    assert combined.is_watertight and len(combined.split(only_watertight=False)) == 1


def test_repaint_changes_only_codes_and_palette(tmp_path):
    box = trimesh.creation.box(extents=[10, 10, 10])
    src = bambu3mf.write([bambu3mf.Part("b", box, 1, paint=["4"] * 12)], ["#111111", "#222222"], tmp_path / "a.3mf")
    new = ["8"] * 6 + [""] * 6
    dst = bambu3mf.repaint(src, tmp_path / "b.3mf", new, ["#AABBCC", "#222222"])
    mesh, codes, palette = bambu3mf.read_painted(dst)
    assert codes == new and palette == ["#AABBCC", "#222222"]
    orig, _, _ = bambu3mf.read_painted(src)
    np.testing.assert_array_equal(mesh.vertices, orig.vertices)
    np.testing.assert_array_equal(mesh.faces, orig.faces)
    with pytest.raises(ValueError, match="codes for 12"):
        bambu3mf.repaint(src, tmp_path / "c.3mf", ["4"] * 3)


def test_figure_base_fills_floating_feature_and_keeps_paint(tmp_path):
    from cad import figure_base

    body = trimesh.creation.box(extents=[10, 10, 30])
    body.apply_translation([0, 0, 15])
    arm = trimesh.creation.box(extents=[4, 4, 20])  # hangs 2 mm above the bottom, beside the body
    arm.apply_translation([9, 0, 12])
    bridge = trimesh.creation.box(extents=[6, 4, 4])
    bridge.apply_translation([6, 0, 20])
    fig = trimesh.boolean.union([body, arm, bridge], engine="manifold")
    paint = ["8"] * len(fig.faces)
    src = bambu3mf.write([bambu3mf.Part("fig", fig, 1, paint=paint)], ["#FF0000", "#00FF00"], tmp_path / "f.3mf")

    parts, info = figure_base.build(src, total_mm=40, base_mm=5, cell_mm=0.5)
    fig_part, base_part = parts
    assert fig_part.paint == paint and base_part.filament == 3
    assert info["total_height_mm"] == pytest.approx(40)
    assert len(info["pedestals"]) == 1 and info["pedestals"][0]["gap_mm"] == pytest.approx(2 * 35 / 30, abs=0.3)
    assert base_part.mesh.is_watertight
    assert fig_part.mesh.bounds[0][2] == pytest.approx(5)


def test_repaint_moves_only_given_vertices(tmp_path):
    box = trimesh.creation.box(extents=[10, 10, 10])
    src = bambu3mf.write([bambu3mf.Part("b", box, 1, paint=["4"] * 12)], ["#111111"], tmp_path / "a.3mf")
    orig, codes, _ = bambu3mf.read_painted(src)
    dst = bambu3mf.repaint(src, tmp_path / "b.3mf", codes, moved={0: (1.5, 2.5, 3.5)})
    mesh, _, _ = bambu3mf.read_painted(dst)
    np.testing.assert_allclose(mesh.vertices[0], [1.5, 2.5, 3.5])
    np.testing.assert_array_equal(mesh.vertices[1:], orig.vertices[1:])
    with pytest.raises(ValueError, match="out of range"):
        bambu3mf.repaint(src, tmp_path / "c.3mf", codes, moved={99: (0, 0, 0)})
