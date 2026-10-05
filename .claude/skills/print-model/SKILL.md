---
name: print-model
description: Generate a 3D-printable model (STL/3MF in mm) from a text prompt or an image using the Meshy AI API, then check and prepare it for FDM printing. Use when the user asks to make, generate, or design something to 3D print.
---

# Generate a printable model with Meshy

The pipeline lives in `meshy3d/` and is driven via `python -m meshy3d`. It costs Meshy credits, so
follow these steps in order.

## 1. Pin down the request

Confirm before spending credits (ask only for what's missing):
- **What** the object is, and whether to work from a text prompt or an image (local .png/.jpg/.jpeg or URL).
- **Size in mm**: either the final height (`--height-mm`) or the longest side (`--longest-mm`).
  Never guess a size; it determines whether the part fits the printer and whether details survive.

## 2. Write a print-friendly prompt (text mode)

Meshy generates the shape from the prompt. Steer it toward geometry FDM can print:
- One solid object, no scene or background props.
- A flat base or broad footprint so it stands on the bed.
- Chunky features; avoid thin, unsupported protrusions (spears, antennae, loose hair strands).
- Name the style when it helps, e.g. "stylized", "low detail", "figurine on a round base".
Use `--negative` for things to avoid (e.g. "thin parts, floating pieces, text").
These are general FDM practices, not Meshy-documented rules; adjust when results say otherwise.

## 3. Check cost, then confirm

```bash
python -m meshy3d balance
python -m meshy3d text "<prompt>" --height-mm 60 --dry-run
python -m meshy3d image path/to/photo.png --longest-mm 80 --dry-run
```

Tell the user the estimated credit range from `--dry-run` and their balance, and get a go-ahead
before the real run unless they already approved spending for this request. Cheaper options:
`--model meshy-6-lite` or `--model meshy-t2` (5 credits vs 20). `--repair auto` (default) adds 10
credits only if Meshy's printability verdict is `error`.

## 4. Run it

Same command without `--dry-run`. Generation takes minutes, so run it with a long Bash timeout
(up to 600000 ms) or in the background. Output goes to `output/<timestamp>-<slug>/`:
`raw.glb`, `repaired.glb` (if repaired), `model.stl`, `model.3mf`, `preview.png`, `thumbnail.png`,
`manifest.json` (task ids, printability verdicts, credits used).

If the run dies after the generation task was created, don't regenerate (that pays again). Resume with
the task id from the printed log or `manifest.json`: `--resume-task <id>`. Meshy keeps assets for
3 days only.

## 5. Review before handing over

- **Look at `preview.png`** (Read it). The model must stand upright with its base on the red build-plate
  line. If it's lying down or upside down, re-run the local prep on the downloaded GLB, no credits needed:
  `python -m meshy3d prep output/<dir>/raw.glb --height-mm 60 --up z` (or `--up y`), then Read the new preview.
- Check `mesh_report.warnings` (not watertight, multiple bodies, under 1 mm) and the Meshy verdict in
  `manifest.json` (`healthy` / `warning` / `error` / `unknown`). Report them plainly; don't call a model
  print-ready if it isn't watertight.
- Supports, infill and wall settings stay in the user's slicer.

## 6. Deliver

Give the user the STL/3MF paths, final dimensions, verdict, warnings, and credits consumed. `output/` is
gitignored; in a Claude Code cloud session the container is temporary, so send the STL/3MF/preview files
to the user directly rather than leaving them on disk.
