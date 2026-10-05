"""Command-line entry point: python -m meshy3d <command> ..."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import images, pipeline, presets, printing
from .client import MeshyClient, MeshyError
from .printprep import ORIENTATIONS


def _add_size_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--height-mm", type=float, help="Final height (Z) in mm")
    p.add_argument("--longest-mm", type=float, help="Final longest side in mm")


def _size(args: argparse.Namespace, required: bool = True) -> tuple[float | None, str]:
    if args.height_mm and args.longest_mm:
        raise ValueError("give only one of --height-mm or --longest-mm")
    if required and not (args.height_mm or args.longest_mm):
        raise ValueError("give one of --height-mm or --longest-mm")
    return (args.height_mm or args.longest_mm), ("longest" if args.longest_mm else "height")


def _add_multicolor_args(p: argparse.ArgumentParser, flag: bool = True) -> None:
    g = p.add_argument_group("multi-color 3MF (10 credits; generation adds +10 for the texture it needs)")
    if flag:
        g.add_argument("--multicolor", action="store_true", help="Also make a multi-color 3MF")
    g.add_argument("--colors", type=int, default=4, help="max_colors, 1-16 (default 4)")
    g.add_argument("--color-style", choices=printing.MULTICOLOR_STYLES, default="realistic",
                   help="realistic samples the texture; cartoon flattens into clean regions")
    g.add_argument("--printer", choices=printing.PRINTER_BRANDS, default="bambu",
                   help="Slicer preset written into the 3MF (default bambu)")
    g.add_argument("--color-depth", type=int, help="max_depth 3-6 (realistic only)")


def _multicolor(args: argparse.Namespace, force: bool = False) -> printing.MultiColorOptions | None:
    if not (force or args.multicolor):
        return None
    return printing.MultiColorOptions(args.colors, args.color_style, args.printer, args.color_depth)


def _add_split_args(p: argparse.ArgumentParser, flag: bool = True) -> None:
    g = p.add_argument_group("auto split into parts (10 credits; Meshy 6/7 models only)")
    if flag:
        g.add_argument("--split", action="store_true", help="Also split into separately printable parts")
    g.add_argument("--split-mode", choices=printing.SPLIT_MODES, default="auto")
    g.add_argument("--split-prompt", help="Name the parts (by_parts/by_color), e.g. 'head, body, base'")
    g.add_argument("--connectors", action="store_true", help="Add mortise-and-tenon connectors at cuts")
    g.add_argument("--connector-type", choices=printing.CONNECTOR_TYPES)
    g.add_argument("--connector-size", type=float, help="0.1-0.8, relative to cut surface")
    g.add_argument("--connector-height", type=float, help="0.1-0.8, relative to cut surface")


def _split(args: argparse.Namespace, force: bool = False) -> printing.SplitOptions | None:
    if not (force or args.split):
        return None
    return printing.SplitOptions(args.split_mode, args.split_prompt, args.connectors, args.connector_type,
                                 args.connector_size, args.connector_height)


def _add_generate_args(p: argparse.ArgumentParser) -> None:
    _add_size_args(p)
    p.add_argument("--model", default="latest", choices=sorted(pipeline.MESH_ONLY_CREDITS),
                   help="Meshy ai_model (default: latest; meshy-6-lite / meshy-t2 are cheapest)")
    p.add_argument("--polycount", type=int, help="target_polycount (Meshy default 30000)")
    p.add_argument("--seed", type=int)
    p.add_argument("--ultra", choices=["2k", "4k"], help="geometry_resolution (+5 credits, needs entitlement)")
    p.add_argument("--repair", choices=pipeline.REPAIR_MODES, default="auto",
                   help="auto = repair only if Meshy's verdict is 'error' (10 credits)")
    p.add_argument("--formats", default="stl,3mf", help="Comma-separated: stl,3mf")
    p.add_argument("--out", type=Path, default=Path("output"))
    p.add_argument("--resume-task", help="Existing generation task id to resume (no new generation charge)")
    p.add_argument("--dry-run", action="store_true", help="Print the request and credit estimate, call nothing")
    _add_multicolor_args(p)
    _add_split_args(p)


def _kv(pairs: list[str] | None) -> dict[str, Any]:
    """Parse key=value pairs; values are JSON when they parse (numbers, booleans), else strings."""
    out: dict[str, Any] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"expected key=value, got {pair!r}")
        try:
            out[key] = json.loads(value)
        except json.JSONDecodeError:
            out[key] = value
    return out


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def _truncate_image(payload: dict) -> dict:
    url = payload.get("image_url", "")
    if url.startswith("data:"):
        payload = {**payload, "image_url": url[:40] + "...(truncated)"}
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meshy3d", description="Meshy AI -> 3D-printable STL/3MF")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("balance", help="Show remaining Meshy credits")

    t = sub.add_parser("text", help="Generate from a text prompt")
    t.add_argument("prompt")
    t.add_argument("--negative", help="negative_prompt")
    t.add_argument("--texture-prompt", help="Texture description (only with --multicolor)")
    _add_generate_args(t)

    i = sub.add_parser("image", help="Generate from an image (local .png/.jpg or URL)")
    i.add_argument("image")
    _add_generate_args(i)

    mi = sub.add_parser("multi-image", help="Generate from 1-4 photos of the same object (front view first)")
    mi.add_argument("images", nargs="+")
    _add_generate_args(mi)

    e = sub.add_parser("edit-image", help="Edit photos with Meshy image-to-image (e.g. remove hand/background)")
    e.add_argument("images", nargs="+", help="Each image is edited separately")
    e.add_argument("--prompt", help="Edit instruction (default: clean product-photo cleanup)")
    e.add_argument("--extra", help="Appended to the prompt, e.g. what the object is")
    e.add_argument("--model", default="nano-banana-2", choices=list(images.EDIT_MODEL_CREDITS))
    e.add_argument("--aspect", choices=images.ASPECT_RATIOS, help="Output aspect ratio (default 1:1)")
    e.add_argument("--out", type=Path, default=Path("output"))
    e.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("prep", help="Print-prep an existing local model (no API calls)")
    p.add_argument("model", type=Path)
    _add_size_args(p)
    p.add_argument("--up", choices=ORIENTATIONS,
                   help="Source up axis: y (glTF default), z, or flat = lay thinnest side down")
    p.add_argument("--flip", action="store_true", help="Turn upside down (180 deg about X)")
    p.add_argument("--formats", default="stl,3mf")
    p.add_argument("--out", type=Path)

    m = sub.add_parser("multicolor", help="Multi-color 3MF from an existing textured Meshy task or GLB URL")
    src = m.add_mutually_exclusive_group(required=True)
    src.add_argument("--task-id", help="Succeeded textured text-to-3d refine / image-to-3d task")
    src.add_argument("--model-url", help="URL of a textured .glb/.fbx")
    _add_size_args(m)
    _add_multicolor_args(m, flag=False)
    m.add_argument("--out", type=Path, default=Path("output"))

    s = sub.add_parser("split", help="Split an existing Meshy model into printable parts")
    s.add_argument("--task-id", required=True, help="Succeeded text-to-3d preview / image-to-3d task")
    _add_size_args(s)
    _add_split_args(s, flag=False)
    s.add_argument("--out", type=Path, default=Path("output"))

    pr = sub.add_parser("preset", help="Creative Lab photo presets (keychain, figure, lamp, ...)")
    psub = pr.add_subparsers(dest="preset_cmd", required=True)
    psub.add_parser("list", help="List presets and credit costs")

    pp = psub.add_parser("prototype", help="Stage 1: photo -> concept image(s) to review")
    pp.add_argument("name", choices=list(presets.PRESETS))
    pp.add_argument("image", help="Local .png/.jpg/.jpeg/.webp or URL")
    pp.add_argument("--param", action="append", metavar="KEY=VALUE",
                    help="Prototype parameter, e.g. name_text=Luna, type=person, image_subject=landscape")
    pp.add_argument("--out", type=Path, default=Path("output"))
    pp.add_argument("--dry-run", action="store_true")

    pb = psub.add_parser("build", help="Stage 2: concept -> 3D model and print files")
    pb.add_argument("name", choices=list(presets.PRESETS))
    where = pb.add_mutually_exclusive_group(required=True)
    where.add_argument("--dir", type=Path, help="Output directory from `preset prototype`")
    where.add_argument("--prototype-task", help="Prototype task id (writes to a new directory)")
    pb.add_argument("--option", action="append", metavar="KEY=VALUE",
                    help="Build option, e.g. size_mm=50, badge_shape=hexagon, grid_size=16")
    pb.add_argument("--format", help="Output format where the preset offers one (glb, obj, zip, stl, 3mf)")
    pb.add_argument("--candidate", help="Keycap candidate id (default: first)")
    _add_size_args(pb)
    pb.add_argument("--flip", action="store_true", help="Turn the print file upside down")
    _add_multicolor_args(pb)
    pb.add_argument("--out", type=Path, default=Path("output"))
    pb.add_argument("--dry-run", action="store_true")

    ps = psub.add_parser("run", help="Single-stage presets (fidget-collapsible)")
    ps.add_argument("name", choices=[n for n, p in presets.PRESETS.items() if not p.two_stage])
    ps.add_argument("image")
    ps.add_argument("--out", type=Path, default=Path("output"))
    ps.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except MeshyError as e:
        print(f"Meshy error: {e}", file=sys.stderr)
        return 1
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    if args.cmd == "balance":
        print(MeshyClient().balance())
        return 0

    if args.cmd == "prep":
        size, axis = _size(args)
        prt = pipeline.PrintOptions(size_mm=size, size_axis=axis,
                                    formats=tuple(f.strip() for f in args.formats.split(",") if f.strip()))
        _print_json(pipeline.prep_local(args.model, prt, args.up, args.out, args.flip))
        return 0

    if args.cmd in ("text", "image", "multi-image"):
        return _generate(args)

    if args.cmd == "edit-image":
        prompt = " ".join(p for p in (args.prompt or images.CLEANUP_PROMPT, args.extra) if p)
        if args.dry_run:
            reqs = [_truncate_image({**pl, "image_url": pl["reference_image_urls"][0]})
                    for pl in (images.edit_payload(i, prompt, args.model, args.aspect) for i in args.images)]
            _print_json({"requests": [{k: v for k, v in r.items() if k != "reference_image_urls"} for r in reqs],
                         "estimated_credits": images.estimate_credits(len(args.images), args.model)})
            return 0
        _print_json(images.edit_images(MeshyClient(), args.images, prompt, args.model, args.aspect, args.out))
        return 0

    if args.cmd == "multicolor":
        size, axis = _size(args, required=False)
        source = {"input_task_id": args.task_id} if args.task_id else {"model_url": args.model_url}
        out_dir = pipeline.new_out_dir(args.out, "multicolor")
        _print_json(printing.run_multicolor(MeshyClient(), source, _multicolor(args, force=True), out_dir, size, axis))
        return 0

    if args.cmd == "split":
        size, axis = _size(args)
        out_dir = pipeline.new_out_dir(args.out, "split")
        _print_json(printing.run_split(MeshyClient(), args.task_id, _split(args, force=True), out_dir, size, axis))
        return 0

    if args.cmd == "preset":
        return _preset(args)
    raise AssertionError(args.cmd)


def _generate(args: argparse.Namespace) -> int:
    size, axis = _size(args)
    prt = pipeline.PrintOptions(
        size_mm=size,
        size_axis=axis,
        formats=tuple(f.strip() for f in args.formats.split(",") if f.strip()),
        repair=args.repair,
        multicolor=_multicolor(args),
        split=_split(args),
        texture_prompt=getattr(args, "texture_prompt", None),
    )
    gen = pipeline.GenerateOptions(
        ai_model=args.model,
        target_polycount=args.polycount,
        negative_prompt=getattr(args, "negative", None),
        seed=args.seed,
        geometry_resolution=args.ultra,
    )
    source = {"text": "prompt", "image": "image", "multi-image": "images"}[args.cmd]
    source = getattr(args, source)
    pipeline.validate(args.cmd, gen, prt)
    low, high = pipeline.estimate_credits(gen, prt.repair, include_generation=not args.resume_task, prt=prt)

    if args.dry_run:
        payload = pipeline.generate_payload(args.cmd, source, gen, textured=prt.multicolor is not None)
        if "image_urls" in payload:
            payload["image_urls"] = [_truncate_image({"image_url": u})["image_url"] for u in payload["image_urls"]]
        _print_json({
            "request": _truncate_image(payload),
            "multicolor": prt.multicolor.__dict__ if prt.multicolor else None,
            "split": prt.split.__dict__ if prt.split else None,
            "size": {"size_mm": size, "size_axis": axis},
            "estimated_credits": [low, high],
        })
        return 0

    print(f"Estimated cost: {low}-{high} credits", file=sys.stderr)
    manifest = pipeline.run(MeshyClient(), args.cmd, source, gen, prt, args.out, args.resume_task)
    summary = {k: manifest.get(k) for k in ("output_dir", "print_files", "preview", "mesh_report", "credits_consumed")}
    for step in ("split", "multicolor"):
        if step in manifest["steps"]:
            summary[step] = manifest["steps"][step]
    _print_json(summary)
    return 0


def _preset(args: argparse.Namespace) -> int:
    if args.preset_cmd == "list":
        _print_json({
            name: {
                "stages": "prototype + build" if p.two_stage else "single",
                "credits": ({"prototype": p.prototype_credits, "build": p.build_credits}
                            if p.two_stage else p.build_credits),
                "makes": p.summary,
                "docs": p.doc_url,
            }
            for name, p in presets.PRESETS.items()
        })
        return 0

    preset = presets.get(args.name)

    if args.preset_cmd == "prototype":
        params = _kv(args.param)
        payload = presets.prototype_payload(preset, args.image, params)
        if args.dry_run:
            _print_json({"request": _truncate_image(payload), "estimated_credits": preset.prototype_credits,
                         "next": f"build costs {preset.build_credits} more"})
            return 0
        manifest = presets.run_prototype(MeshyClient(), preset, args.image, params, args.out)
        _print_json(manifest)
        return 0

    if args.preset_cmd == "build":
        size, axis = _size(args, required=False)
        options = _kv(args.option)
        multicolor = _multicolor(args)
        if args.dry_run:
            proto_id = args.prototype_task or presets.load_manifest(args.dir)["steps"]["prototype"]["task_id"]
            candidate = args.candidate or ("<first candidate>" if preset.name == "keycap" else None)
            body = presets.build_payload(preset, proto_id, options, args.format, candidate)
            credits = preset.build_credits + (printing.MULTICOLOR_CREDITS if multicolor else 0)
            _print_json({"request": body, "size": {"size_mm": size, "size_axis": axis},
                         "multicolor": multicolor.__dict__ if multicolor else None, "estimated_credits": credits})
            return 0
        out_dir = args.dir or presets.new_out_dir(args.out, preset, args.prototype_task)
        manifest = presets.run_build(
            MeshyClient(), preset, out_dir, args.prototype_task, options, args.format, args.candidate,
            size, axis, args.flip, multicolor,
        )
        _print_json(manifest)
        return 0

    if args.preset_cmd == "run":
        if args.dry_run:
            payload = {"image_url": presets.image_to_url(args.image, presets.PRESET_IMAGE_MIMES)}
            _print_json({"request": _truncate_image(payload), "estimated_credits": preset.build_credits})
            return 0
        _print_json(presets.run_single(MeshyClient(), preset, args.image, args.out))
        return 0
    raise AssertionError(args.preset_cmd)
