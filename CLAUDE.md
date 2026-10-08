# Salsa3D

Pipeline that turns text prompts or images into 3D-printable files with the Meshy AI API.
To generate a model, follow the `/print-model` skill (`.claude/skills/print-model/SKILL.md`).
When the user brings a photo, follow `/photo-to-print` (`.claude/skills/photo-to-print/SKILL.md`).

## Layout

- `meshy3d/client.py`: Meshy REST client (auth, task polling with `Retry-After`, 429 retries, downloads).
- `meshy3d/pipeline.py`: generate -> analyze printability (free) -> repair if verdict is `error` -> local prep. Writes `manifest.json`.
- `meshy3d/printing.py`: Meshy multi-color 3MF and auto split into parts.
- `meshy3d/presets.py`: Creative Lab photo presets (table `PRESETS`), prototype -> build, per-preset post-processing.
- `meshy3d/printprep.py`: local, credit-free: GLB (meters, Y-up) -> Z-up, scaled to mm, on the bed; multi-part layout; STL/3MF export; preview render.
- `meshy3d/cli.py`: `python -m meshy3d {balance,text,image,multi-image,generate-image,edit-image,prep,multicolor,split,preset}`. JSON result on stdout, progress on stderr.
- `meshy3d/images.py`: Meshy 2D images: `edit-image` (per-photo cleanup) and `generate-image` (text and/or up to
  5 reference photos, optional 3-view sheet); generated images feed 3D via `--from-image-task`.
- `meshy3d/bambu3mf.py`: write/read multi-part Bambu Studio 3MF files with one filament per part.
- `cad/`: parametric models built from scratch (no Meshy), e.g. `python -m cad.isolator`. Constants at the top of
  each file are the dimensions; output goes to `output/cad-<name>/` with a color render, print preview and checks
  (watertight parts, no overlaps between colors).
- `cad/figure_base.py`: put a painted multi-color figure 3MF on a plain CAD base (extra filament slot), filling
  small gaps under floating features. `bambu3mf.repaint` rewrites per-triangle paint codes (e.g. recolor a region).
- `cad/name_tag.py` + `cad/pixelfont.py`: Minecraft-style round name tag (pixel font drawn in-repo; add glyphs to
  `GLYPHS` for new letters). `python -m cad.name_tag --line1 ... --line2 ...`.
- `tests/`: offline tests against a fake Meshy API (`tests/fakes.py`). No key or credits needed.

## Conventions

- API key comes from the `MESHY_API_KEY` env var. Never print it, log it, or write it to files.
- Anything that calls Meshy costs credits except `balance` and print analysis. Validate inputs before the
  first paid call so a bad combination never wastes credits. Use `--dry-run` and
  confirm with the user before spending.
- API reference: https://docs.meshy.ai/llms.txt and the OpenAPI spec at https://docs.meshy.ai/openapi.json.
  Creative Lab endpoints are not in the OpenAPI spec; use https://docs.meshy.ai/api/creative-lab-<name>.md.
  Check them before adding endpoints or parameters; prices in `pipeline.py` are from the docs and may drift.
- Run tests: `python -m pytest -q`. Lint: `ruff check meshy3d tests`.
