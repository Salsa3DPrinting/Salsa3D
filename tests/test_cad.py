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
