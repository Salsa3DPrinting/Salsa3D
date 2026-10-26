"""Build the Kanto world: python -m kanto [--out DIR] [--creative]

Writes DIR/Kanto/ (world folder), DIR/Kanto.mcworld (import into Minecraft Bedrock, then upload to a Realm),
and two map renders. Prints a JSON summary on stdout.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kanto import gym_puzzle, places
from kanto.level import ADVENTURE, CREATIVE, level_dat
from kanto.render import render

PACK = Path(__file__).parent / "pack" / "KantoScripts"
FLAT = [("bedrock", 1), ("dirt", 3), ("grass_block", 1)]  # ground top at y -60 outside the build, like Pallet


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("output/kanto"))
    ap.add_argument("--creative", action="store_true", help="default game mode Creative instead of Adventure")
    args = ap.parse_args(argv)

    grid = gym_puzzle.layout()
    if gym_puzzle.goal(grid) not in gym_puzzle.solve(grid):
        raise SystemExit("gym maze has no solution")
    w = places.build()
    args.out.mkdir(parents=True, exist_ok=True)
    level = level_dat("Kanto", places.SPAWN, FLAT, game_type=CREATIVE if args.creative else ADVENTURE)
    mcworld = w.write(args.out / "Kanto", level, pack_dir=PACK)
    b = places.BOUNDS
    surface = render(w, b, args.out / "map_roofs.png")
    plan = render(w, b, args.out / "map_floorplan.png", cut={k: v + 2 for k, v in w.ground.items()})
    summary = {
        "mcworld": str(mcworld),
        "size_mb": round(mcworld.stat().st_size / 1e6, 2),
        "chunks": len(w.chunks),
        "block_types": len(w.palette),
        "signs": len(w.meta.get("signs", [])),
        "buttons": len(w.meta.get("buttons", [])),
        "spawn": places.SPAWN,
        "renders": [str(surface), str(plan)],
    }
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
