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


def test_name_tag_builds_clean():
    from cad import name_tag
    from cad.pixelfont import text_pixels

    parts, layout = name_tag.build("M. Rodriguez", "Room 14")
    assert all(layout[k] for k in ("text_inside_rim", "creeper_inside_rim", "text_clear_of_hole",
                                   "text_clear_of_creeper"))
    report = name_tag.check(parts)
    assert report["overlaps_mm3"] == {}
    assert all(p["watertight"] for p in report["parts"].values())
    assert report["extents_mm"] == pytest.approx([63.5, 63.5, 2.0], abs=1e-3)
    with pytest.raises(ValueError, match="no glyph"):
        text_pixels("Zoë")


def test_rack_mount_fits_pc_and_rack():
    from cad import rack_mount_10in as r

    body, info = r.build()
    assert body.is_watertight and len(body.split(only_watertight=False)) == 1
    assert info["tray_fits_rail_opening"]
    lo, hi = info["slot_center_range_mm"]
    assert lo <= 238.0 and hi >= 242.0  # user's rack measured ~240 mm center-to-center, +-2 mm
    for dev in (r.pc_dummy(), r.kvm_dummy()):
        inter = trimesh.boolean.intersection([body, dev], engine="manifold")
        assert (inter.volume if len(inter.faces) else 0) < 1e-3
    # The two windows sit side by side inside the rails, with a wall between them.
    lay = r.layout()
    # Zip-tie slots go through the floor behind the JetKVM; the floor next to them is solid.
    kmid, fz = sum(lay["kvm"]) / 2, r.floor_top() - r.FLOOR_T / 2
    holes = [[kmid + s * r.TIE_SPAN / 2, r.TIE_Y, fz] for s in (-1, 1)]
    assert not body.contains(holes).any() and body.contains([[kmid, r.TIE_Y, fz]]).all()
    assert r.TIE_Y - r.TIE_L / 2 > r.KVM_D - r.KVM_HEAD_D
    assert lay["kvm"][0] - lay["pc"][1] >= 10 and -r.OPENING_W / 2 < lay["outer"][0] and lay["outer"][1] < r.OPENING_W / 2
    assert body.extents == pytest.approx([254.0, 112.0, 88.11], abs=0.01)
    # Rounded faceplate corners: the old sharp corners are gone, the edges are not.
    x1, z0, z1 = r.PANEL_W / 2, 0.79 / 2, 0.79 / 2 + r.PANEL_H
    probes = [[x1 - 0.3, 1.0, z0 + 0.3], [-x1 + 0.3, 1.0, z1 - 0.3], [x1 - 0.3, 1.0, 44.0]]
    assert body.contains(probes).tolist() == [False, False, True]


def test_soldier_puzzle_fits_and_prints(tmp_path):
    from shapely.ops import unary_union

    from cad import puzzle_soldier as ps
    from meshy3d import bambu3mf

    parts, info, pieces = ps.build()
    assert info["piece_count"] == 8
    assert all(p.mesh.is_watertight for p in parts)
    allm = trimesh.util.concatenate([p.mesh for p in parts])
    assert allm.extents[0] <= ps.PLATE and allm.extents[1] <= ps.PLATE
    for i, a in enumerate(parts):  # no two filaments share volume
        for b in parts[i + 1:]:
            inter = trimesh.boolean.intersection([a.mesh, b.mesh], engine="manifold")
            assert (inter.volume if len(inter.faces) else 0) < 1e-3, (a.name, b.name)
    # Every piece fits its spot with clearance and stays clear of the other pieces' spots.
    for p in pieces:
        o = ps.piece_outline(p["shape"])
        assert p["shape"].buffer(-ps.CLEAR + 1e-6).contains(o)
    outlines = [ps.piece_outline(p["shape"]) for p in pieces]
    assert ps.overlaps(outlines) == 0
    assert unary_union([p["shape"] for p in pieces]).bounds[3] == pytest.approx(ps.HEIGHT)
    assert info["board_wall_area_thinner_than_3mm_mm2"] < 10  # only small corner notches
    path = tmp_path / "puzzle.3mf"
    bambu3mf.write(parts, ps.PALETTE, path)
    back = bambu3mf.read_parts(path)
    assert sorted(p["filament"] for p in back) == list(range(1, 9))
    assert sum(len(p["mesh"].faces) for p in back) == sum(len(p.mesh.faces) for p in parts)


def test_wizard_staff_segments_join_and_clear_the_pvc():
    from cad import wizard_staff as w

    a, b = w.shaft_segment(0), w.shaft_segment(1)
    for m in (a, b):
        assert m.is_watertight and len(m.split(only_watertight=False)) == 1
        assert m.extents[2] <= w.MAX_PRINT_H
    inter = trimesh.boolean.intersection([a, b], engine="manifold")
    assert (inter.volume if len(inter.faces) else 0) < 1e-3          # spigot fits its socket
    pipe = w.cyl(w.PVC_OD / 2, w.FOOT_T + 1, w.joints()[2] - 1)
    assert (w.to_m(a) ^ pipe).volume() + (w.to_m(b) ^ pipe).volume() < 1e-3
    assert a.contains([[0, 0, w.FOOT_T / 2]]).all()                   # closed foot hides the pipe
    assert w.min_wall() >= 6.0
    assert w.joints()[-1] + w.HEAD_H == pytest.approx(w.TOTAL_H)
