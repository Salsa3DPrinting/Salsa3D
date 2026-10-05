# Salsa3D

Generate 3D-printable models with [Meshy AI](https://www.meshy.ai/), driven by Claude Code.

```
prompt / image ──► Meshy generate (geometry only)
                   ──► Meshy analyze printability (free)
                   ──► Meshy repair (only if verdict = error, 10 credits)
                   ──► local: orient Z-up, scale to mm, place on bed
                   ──► model.stl + model.3mf + preview.png + manifest.json
```

Sizing and STL/3MF export happen locally because Meshy outputs glTF (meters, Y-up) and slicers expect
millimeters, Z-up. Doing it locally makes the final size exact and verifiable, and it's free.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export MESHY_API_KEY=msy_...   # from https://www.meshy.ai/developers/keys
```

In Claude Code cloud sessions, the SessionStart hook in `.claude/` installs dependencies automatically,
and `MESHY_API_KEY` is set as an environment variable in the cloud environment's settings.

## Use

With Claude Code: ask for a model (e.g. "make me a 50 mm tall owl figurine") or run `/print-model`.

Directly:

```bash
python -m meshy3d balance
python -m meshy3d text "a chunky owl figurine on a round base" --height-mm 50 --dry-run
python -m meshy3d text "a chunky owl figurine on a round base" --height-mm 50
python -m meshy3d image photo.png --longest-mm 80 --model meshy-6-lite
python -m meshy3d prep some_model.glb --height-mm 40      # local only, no credits
```

Options: `--model` (`latest`, `meshy-7.1`, `meshy-6`, `meshy-6-lite`, `meshy-t2`), `--polycount`,
`--seed`, `--ultra 2k|4k`, `--repair auto|always|never`, `--formats stl,3mf`, `--resume-task <id>`.

Estimated credits per run (from Meshy's pricing page, Oct 2026): 20 with `latest`/`meshy-6`, 5 with
`meshy-6-lite`/`meshy-t2`, +10 if repaired, +5 for Ultra geometry. Meshy keeps generated assets for
3 days; the pipeline downloads everything into `output/`.

## Tests

```bash
python -m pytest -q
```
