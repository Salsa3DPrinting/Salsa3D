# Salsa3D

Generate 3D-printable models with [Meshy AI](https://www.meshy.ai/), driven by Claude Code.

```
prompt / image ──► Meshy generate (geometry only)
                   ──► Meshy analyze printability (free)
                   ──► Meshy repair (only if verdict = error, 10 credits)
                   ──► local: orient Z-up, scale to mm, place on bed
                   ──► model.stl + model.3mf + preview.png + manifest.json
```

Optional extras: a multi-color 3MF for multi-filament printers (`--multicolor`), auto split into
separately printable parts (`--split`), and Meshy's Creative Lab photo presets (keychain, fridge
magnet, figures, lamp, keycap, fidget toys).

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
For a photo, share it and say what you want (a replica, keychain, magnet, figure...) or run `/photo-to-print`.

Directly:

```bash
python -m meshy3d balance
python -m meshy3d text "a chunky owl figurine on a round base" --height-mm 50 --dry-run
python -m meshy3d text "a chunky owl figurine on a round base" --height-mm 50
python -m meshy3d image photo.png --longest-mm 80 --model meshy-6-lite
python -m meshy3d prep some_model.glb --height-mm 40      # local only, no credits

# multi-color 3MF and/or split into parts
python -m meshy3d text "a parrot on a perch" --height-mm 80 --multicolor --colors 4 --printer prusa
python -m meshy3d text "a robot" --height-mm 200 --split --split-mode by_parts --split-prompt "head, torso, arms, legs" --connectors

# Creative Lab presets: review the concept, then build
python -m meshy3d preset list
python -m meshy3d preset prototype keychain dog.jpg --param name_text=Rex
python -m meshy3d preset build keychain --dir output/<dir> --option size_mm=45
```

Options: `--model` (`latest`, `meshy-7.1`, `meshy-6`, `meshy-6-lite`, `meshy-t2`), `--polycount`,
`--seed`, `--ultra 2k|4k`, `--repair auto|always|never`, `--formats stl,3mf`, `--resume-task <id>`.

Estimated credits per run (from Meshy's pricing page, Oct 2026): 20 with `latest`/`meshy-6`, 5 with
`meshy-6-lite`/`meshy-t2`, +10 if repaired, +5 for Ultra geometry, +20 for multi-color (texture +
conversion), +10 for split. Presets: see `python -m meshy3d preset list`. Meshy keeps generated assets for
3 days; the pipeline downloads everything into `output/`.

## Tests

```bash
python -m pytest -q
```
