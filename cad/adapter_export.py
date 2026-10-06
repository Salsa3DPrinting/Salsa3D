"""Export the adapter tool's data, sample API payloads and test vectors as JSON for the handoff spec.

The files in docs/adapter-tool-handoff/ are generated from the code so the spec can't drift from it;
tests/test_adapter_app.py checks that the checked-in data file matches.

Run: python -m cad.adapter_export [--out docs/adapter-tool-handoff]
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict, replace
from pathlib import Path

from cad import adapter, fanlib
from cad.adapter_app import server

OUT = Path("docs/adapter-tool-handoff")

# (side A, side B, options overrides) for the test vectors: one of each fitting kind plus a contraction,
# a big flare that needs the straight neck, and a non-default taper.
VECTOR_CASES = [
    ("bfs-i06", "pvc-4-sch40-spigot", {}),
    ("bfs-i06", "pvc-1-1/2-sch40-socket", {}),
    ("bfs-i06", "pvc-6-sch40-spigot", {}),
    ("bfs-i06", "triclamp-1-1/2", {}),
    ("bfs-i06", "triclamp-1-1/2", {"taper_deg": 37}),
    ("bfs-i06", "npt-2-male", {}),
    ("bfs-i06", "npt-2-female", {}),
    ("triclamp-1-1/2", "npt-2-male", {}),
]

SOURCES = {
    "pipe_od_in": "ASTM D1785 / NPS standard pipe outside diameters (also D in the NPT formulas).",
    "pvc_sch40_socket_depth_in": "ASTM D2466 Schedule 40 socket depth, as listed in Charlotte Pipe's Sch 40 PVC "
                                 "submittal (4 in: entrance 4.518, bottom 4.491, +/-0.009, depth 2.000).",
    "npt": "ASME B1.20.1. tpi and L1 (hand-tight engagement) from the standard's table; E0 = D - (0.05 D + 1.1) p "
           "and L2 = (0.8 D + 6.8) p are the standard's formulas (they reproduce the tabulated values).",
    "triclamp": "Flange OD, tube OD and tube ID from the common tri-clamp sizing chart; gasket bead diameter from "
                "tri-clamp gasket dimension charts (1.5 in = 1.718 in, which matches the groove on the user's working "
                "adapter exactly).",
    "triclamp_profile": "NOT from a standard: rim thickness, 20 deg bevel and groove cross-section measured on the "
                        "user's working BFS-i06 to 1.5 in tri-clamp adapter, applied to every size. Fit-test first.",
    "fans": "bfs-i06 from the manufacturer drawing plus the user's answers; hub plate diameter (70 mm) assumed.",
}


def data() -> dict:
    a = adapter
    return {
        "generator_version": a.GENERATOR_VERSION,
        "units": "mm unless the key ends in _in (inches) or _deg (degrees)",
        "sources": SOURCES,
        "constants": {
            "flange_t": a.FLANGE_T, "bolt_access": a.BOLT_ACCESS, "bolt_keepout_factor": a.BOLT_KEEPOUT_FACTOR,
            "hub_clearance": a.HUB_CLEARANCE, "spigot_extra": a.SPIGOT_EXTRA, "spigot_chamfer": a.SPIGOT_CHAMFER,
            "socket_stop": a.SOCKET_STOP, "fit_test_ring_h": a.FIT_TEST_RING_H, "fit_test_steps": a.FIT_TEST_STEPS,
            "triclamp_profile": a.TRICLAMP_PROFILE, "triclamp_min_wall": a.TRICLAMP_MIN_WALL,
            "triclamp_neck": a.TRICLAMP_NECK, "npt_fine_tpi": a.NPT_FINE_TPI, "npt_extra_threads": a.NPT_EXTRA_THREADS,
            "npt_male_wall": a.NPT_MALE_WALL, "npt_female_wall": a.NPT_FEMALE_WALL, "npt_collar": a.NPT_COLLAR,
        },
        "options": {
            "defaults": asdict(a.DEFAULT),
            "limits": {"taper_deg": [0, 45, "exclusive min"], "wall": [1.2, 10], "spigot_allowance": [-2, 1],
                       "socket_clearance": [0, 3], "npt_clearance": [0, 0.5]},
        },
        "tables": {
            "pipe_od_in": {a.size_label(k): v for k, v in a.PIPE_OD_IN.items()},
            "pvc_sch40_socket_depth_in": {a.size_label(k): v for k, v in a.SCH40_SOCKET_DEPTH_IN.items()},
            "npt": {a.size_label(k): {"tpi": t, "L1_in": l1} for k, (t, l1) in a.NPT.items()},
            "triclamp": {a.size_label(k): {"flange_od_in": f, "tube_od_in": o, "tube_id_in": i, "gasket_bead_d_in": b}
                         for k, (f, o, i, b) in a.TRICLAMP.items()},
        },
        "printers": {k: list(v) for k, v in a.PRINTERS.items()},
        "fittings": a.catalog(),
        "fan_fields": {k: {"label": v[0], "help": v[1], "min": v[2], "max": v[3]}
                       for k, v in fanlib.NUMERIC_FIELDS.items()},
        "builtin_fans": [server.fan_json(f) for f in fanlib.load(None).values()],
    }


def vectors() -> list[dict]:
    fans = fanlib.load(None)
    out = []
    for a_spec, b_spec, over in VECTOR_CASES:
        opt = replace(adapter.DEFAULT, **over)
        lay = adapter.layout(adapter.parse_fitting(a_spec, fans, opt), adapter.parse_fitting(b_spec, fans, opt), opt)
        a, b = lay["a"], lay["b"]
        out.append({
            "input": {"a": a_spec, "b": b_spec, "options": over},
            "expect": {
                "bottom": a.label, "top": b.label,
                "overall_length_mm": round(lay["top"], 2),
                "transition": {"from_id": round(2 * a.join_inner_r, 2), "to_id": round(2 * b.join_inner_r, 2),
                               "straight_neck": round(lay["straight_neck"], 2),
                               "taper_length": round(lay["taper_len"], 2)},
                "bottom_info": a.info, "top_info": b.info,
                "warnings": [*a.warnings, *b.warnings],
                # Half-section profile (radius, z) from the bed up; draw both sides mirrored for a section view.
                "outer_profile": [[round(r, 3), round(z, 3)] for r, z in lay["outer"]],
                "inner_profile": [[round(r, 3), round(z, 3)] for r, z in lay["inner"]],
            },
        })
    return out


def examples() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        state = server.State(Path(tmp))
        report = server.generate(state, {"a": "bfs-i06", "b": "pvc-4-sch40-spigot"})
    report["folder"] = "C:\\Users\\<you>\\AppData\\Roaming\\SalsaAdapter\\output\\" + report["job"]
    return {
        "generate_request": {"a": "bfs-i06", "b": "pvc-4-sch40-spigot", "options": {"taper_deg": 15}},
        "generate_response": report,
        "generate_error": {"error": "'pvc-5-sch40-spigot': no PVC data for 5 in; known sizes: 1/2, 3/4, 1, "
                                    "1-1/4, 1-1/2, 2, 2-1/2, 3, 4, 6, 8, 10, 12"},
        "add_fan_request": {"fan": {"name": "ACME 80 x 25", "frame": 80, "corner_r": 5, "depth": 25, "hole_d": 4.5,
                                    "bore_d": 76, "hub_d": 30, "hub_proud": 0, "hole_spacing": 71.5,
                                    "bolt_circle_d": "", "added_by": "J. Smith", "notes": "Datasheet rev B",
                                    "verified": False},
                            "overwrite": False},
        "add_fan_errors": {"errors": ["Air opening must be smaller than the frame.",
                                      "Holes are too close to the air opening to leave room for the adapter wall."]},
    }


def write(out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    files = {"adapter-data.json": data(), "test-vectors.json": vectors(), "api-examples.json": examples()}
    paths = []
    for name, obj in files.items():
        p = out / name
        p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        paths.append(p)
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    for p in write(ap.parse_args(argv).out):
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
