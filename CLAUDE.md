# Salsa3D

Pipeline that turns text prompts or images into 3D-printable files with the Meshy AI API.
To generate a model, follow the `/print-model` skill (`.claude/skills/print-model/SKILL.md`).

## Layout

- `meshy3d/client.py`: Meshy REST client (auth, task polling with `Retry-After`, 429 retries, downloads).
- `meshy3d/pipeline.py`: generate -> analyze printability (free) -> repair if verdict is `error` -> local prep. Writes `manifest.json`.
- `meshy3d/printprep.py`: local, credit-free: GLB (meters, Y-up) -> Z-up, scaled to mm, on the bed; STL/3MF export; preview render.
- `meshy3d/cli.py`: `python -m meshy3d {balance,text,image,prep}`.
- `tests/`: offline tests against a fake Meshy API (`tests/fakes.py`). No key or credits needed.

## Conventions

- API key comes from the `MESHY_API_KEY` env var. Never print it, log it, or write it to files.
- Anything that calls Meshy costs credits except `balance` and print analysis. Use `--dry-run` and
  confirm with the user before spending.
- API reference: https://docs.meshy.ai/llms.txt and the OpenAPI spec at https://docs.meshy.ai/openapi.json.
  Check them before adding endpoints or parameters; prices in `pipeline.py` are from the docs and may drift.
- Run tests: `python -m pytest -q`. Lint: `ruff check meshy3d tests`.
