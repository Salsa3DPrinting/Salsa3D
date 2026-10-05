"""Command-line entry point: python -m meshy3d <command> ..."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import pipeline
from .client import MeshyClient, MeshyError


def _add_generate_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--height-mm", type=float, help="Final height (Z) in mm")
    p.add_argument("--longest-mm", type=float, help="Final longest side in mm")
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


def _print_opts(args: argparse.Namespace) -> pipeline.PrintOptions:
    if bool(args.height_mm) == bool(args.longest_mm):
        sys.exit("error: give exactly one of --height-mm or --longest-mm")
    return pipeline.PrintOptions(
        size_mm=args.height_mm or args.longest_mm,
        size_axis="height" if args.height_mm else "longest",
        formats=tuple(f.strip() for f in args.formats.split(",") if f.strip()),
        repair=getattr(args, "repair", "auto"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meshy3d", description="Meshy AI -> 3D-printable STL/3MF")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("balance", help="Show remaining Meshy credits")

    t = sub.add_parser("text", help="Generate from a text prompt")
    t.add_argument("prompt")
    t.add_argument("--negative", help="negative_prompt")
    _add_generate_args(t)

    i = sub.add_parser("image", help="Generate from an image (local .png/.jpg or URL)")
    i.add_argument("image")
    _add_generate_args(i)

    p = sub.add_parser("prep", help="Print-prep an existing local model (no API calls)")
    p.add_argument("model", type=Path)
    p.add_argument("--height-mm", type=float)
    p.add_argument("--longest-mm", type=float)
    p.add_argument("--up", choices=["y", "z"], help="Source up axis (default: y for glb/gltf, z otherwise)")
    p.add_argument("--formats", default="stl,3mf")
    p.add_argument("--out", type=Path)

    args = parser.parse_args(argv)

    try:
        if args.cmd == "balance":
            print(MeshyClient().balance())
            return 0

        if args.cmd == "prep":
            result = pipeline.prep_local(args.model, _print_opts(args), args.up, args.out)
            print(json.dumps(result, indent=2))
            return 0

        prt = _print_opts(args)
        gen = pipeline.GenerateOptions(
            ai_model=args.model,
            target_polycount=args.polycount,
            negative_prompt=getattr(args, "negative", None),
            seed=args.seed,
            geometry_resolution=args.ultra,
        )
        source = args.prompt if args.cmd == "text" else args.image
        low, high = pipeline.estimate_credits(gen, prt.repair, include_generation=not args.resume_task)

        if args.dry_run:
            payload = pipeline.text_payload(source, gen) if args.cmd == "text" else pipeline.image_payload(source, gen)
            if "image_url" in payload and payload["image_url"].startswith("data:"):
                payload["image_url"] = payload["image_url"][:40] + "...(truncated)"
            print(json.dumps({"request": payload, "print_options": prt.__dict__,
                              "estimated_credits": [low, high]}, indent=2))
            return 0

        print(f"Estimated cost: {low}-{high} credits")
        manifest = pipeline.run(MeshyClient(), args.cmd, source, gen, prt, args.out, args.resume_task)
        print(json.dumps({k: manifest[k] for k in ("output_dir", "print_files", "preview", "mesh_report", "credits_consumed")},
                         indent=2))
        return 0
    except MeshyError as e:
        print(f"Meshy error: {e}", file=sys.stderr)
        return 1
