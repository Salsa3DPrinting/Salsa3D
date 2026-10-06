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


def test_adapter_fan_to_4in_pvc_spigot():
    from cad import adapter

    mesh, lay = adapter.build("bfs-i06", "4in sch40 pvc spigot")
    report = adapter.check(mesh, lay)
    assert report["watertight"] and report["bodies"] == 1 and report["warnings"] == []
    assert report["extents_mm"][:2] == [120.0, 120.0]
    assert report["fittings"]["top"]["spigot_od"] == pytest.approx(4.5 * 25.4 + adapter.SPIGOT_DIAMETRAL_ALLOWANCE)
    assert report["fittings"]["top"]["spigot_length"] >= 2.0 * 25.4  # D2466 4" socket depth
    # Bolt holes on the Ø138 circle at 45 deg go all the way through the flange.
    for x, y in [(48.79, 48.79), (-48.79, 48.79), (-48.79, -48.79), (48.79, -48.79)]:
        assert not mesh.contains([[x, y, adapter.FLANGE_T / 2]])[0]
    assert mesh.contains([[60 - 1, 0, adapter.FLANGE_T / 2]])[0]  # flange material at the frame edge
    assert report["bolt_access"]["ok"] and report["hub_clearance"]["ok"]


def test_adapter_parse_and_contraction():
    from cad import adapter

    assert adapter.parse_fitting("pvc-1-1/2-sch40-socket").label == "1-1/2 in Sch 40 PVC socket"
    for bad in ("pvc-5-sch40-spigot", "pvc-4-sch80-spigot", "pvc-4-spigot", "flange-6"):
        with pytest.raises(ValueError):
            adapter.parse_fitting(bad)
    mesh, lay = adapter.build("pvc-1-1/2-sch40-socket", "bfs-i06")  # order doesn't matter: fan goes on the bed
    assert lay["a"].kind == "fan"
    assert mesh.is_watertight
    assert lay["taper_len"] == pytest.approx((50 - lay["b"].join_inner_r) / np.tan(np.radians(adapter.TAPER_HALF_ANGLE)))


def _crest_angle(mesh, z, outer):
    loops = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1]).discrete
    pick = max if outer else min
    loop = pick(loops, key=lambda e: np.hypot(e[:, 0], e[:, 1]).max())
    r = np.hypot(loop[:, 0], loop[:, 1])
    crest = loop[r > r.max() - 0.05]  # the truncated crest/root is a short flat: take its middle
    return np.degrees(np.arctan2(crest[:, 1].mean(), crest[:, 0].mean()))


@pytest.mark.parametrize("spec,male", [("npt-2-male", True), ("2in fnpt", False)])
def test_adapter_npt_thread_end(spec, male):
    from cad import adapter

    end = adapter.parse_fitting(spec)
    assert end.kind == ("npt-male" if male else "npt-female")
    ((_, piece),) = adapter.fit_test_pieces(end)
    assert piece.is_watertight and len(piece.split(only_watertight=False)) == 1
    top = piece.bounds[1][2]
    pitch = 25.4 / 11.5
    # Right-hand thread: the crest angle advances +360 deg per pitch going up (face at the top).
    z = top - 10
    step = np.mod(_crest_angle(piece, z + 0.5, male) - _crest_angle(piece, z, male), 360)
    assert step == pytest.approx(0.5 / pitch * 360, abs=3)
    if male:
        # Major diameter at the tip: E0 + 0.8 p, less the print clearance.
        assert end.info["major_d_at_tip"] == pytest.approx(2.26902 * 25.4 + 0.8 * pitch - 2 * adapter.NPT_RADIAL_CLEARANCE,
                                                          abs=0.01)


def test_adapter_triclamp_end():
    from cad import adapter

    mesh, lay = adapter.build("bfs-i06", "1.5in tri-clamp")
    assert mesh.is_watertight and len(mesh.split(only_watertight=False)) == 1
    top = lay["top"]
    assert mesh.extents[2] == pytest.approx(top)
    assert not mesh.contains([[43.64 / 2, 0, top - 0.8]])[0]  # gasket groove
    assert mesh.contains([[25.0, 0, top - 1.0]])[0]           # flange rim, Ø50.4
    assert not mesh.contains([[25.0, 0, top - 8.0]])[0]       # behind the bevel: clamp room


def test_fitting_tables():
    from cad import adapter

    # B1.20.1 formulas reproduce the standard's tabulated E0 / L2.
    for size, e0, l2 in [(0.5, 0.75843, 0.5337), (1.0, 1.21363, 0.6828), (2.0, 2.26902, 0.7565), (4.0, 4.33438, 1.3)]:
        d = adapter.npt_dims(size)
        assert d["E0"] == pytest.approx(e0, abs=1e-5) and d["L2"] == pytest.approx(l2, abs=1e-4)
    end = adapter.parse_fitting("triclamp-2")
    assert end.info["flange_od"] == pytest.approx(2.516 * 25.4, abs=0.01)
    assert end.info["gasket_bead_d"] == pytest.approx(2.218 * 25.4, abs=0.01)
    cat = adapter.catalog()
    assert [s["size"] for s in cat["npt-male"]["sizes"]][:3] == ["1/8", "1/4", "3/8"]
    for kind in cat.values():  # every listed spec parses
        for s in kind["sizes"]:
            adapter.parse_fitting(s["spec"])
