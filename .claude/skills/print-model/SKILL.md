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

## 2b. Optional: make reference images first

Text straight to 3D works, but generating a reference image first lets the user see and approve the
design cheaply (3-12 credits) before paying for 3D (20-30):

```bash
python -m meshy3d generate-image "<prompt>, single object, plain white background" --count 3 --dry-run
python -m meshy3d generate-image "<prompt>, ..." --count 3            # 3 variants to choose from
python -m meshy3d generate-image "<same object>" --from-image-task <chosen task> --multi-view  # 3 views
```

Read every `gen-*.png`, show the user, and build from the chosen task without downloading anything:
`python -m meshy3d image --from-image-task <id> --height-mm 60` (one image) or
`python -m meshy3d multi-image --from-image-task <multi-view id> --height-mm 60` (front view first).
Generated views are invented, not photographed; say so when they fill in sides or backs.

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

### Optional: multi-color 3MF (`--multicolor`, +20 credits)

For multi-filament printers (AMS/MMU etc.). Meshy needs a textured model for this, so the run adds a
texture step (+10) and the multi-color conversion (+10). Ask how many filament colors they have
(`--colors`, 1-16, default 4) and which slicer brand (`--printer`, default bambu, which writes that
brand's slicer preset into the file). `--color-style cartoon` flattens colors into clean regions;
`realistic` (default) samples the texture. Text mode can steer colors with `--texture-prompt`.

The multi-color 3MF is Meshy's own file and is **not rescaled** (rescaling could break the slicer
presets inside it). The result reports its measured size and `slicer_scale_percent`: tell the user
to scale it by that percentage in the slicer. The measurement assumes the 3MF is Z-up in mm, which
hasn't been confirmed on a real Meshy file yet, so ask them to check the size the slicer shows.

### Optional: split into parts (`--split`, +10 credits)

For models larger than the build plate, or to print parts in different colors or orientations.
Only `latest`, `meshy-7.1` or `meshy-6` models (not the cheap ones). Modes: `auto` (Meshy picks
cuts); `by_parts --split-prompt "head, torso, arms, base"` (1-10 named parts); `by_color` (image
mode only). `--connectors` adds pegs and sockets at the cuts. Parts are scaled together so the
assembled model is the requested size, then laid in a row on the plate as `parts/part-NN-*.stl` and
`parts/parts.3mf`. Meshy's docs say the split result loses textures, so split parts print in
single colors.

### Already generated?

To add these to an earlier run without regenerating, use the task id from its `manifest.json`:
`python -m meshy3d split --task-id <generate task> --height-mm 60` or
`python -m meshy3d multicolor --task-id <textured task> --height-mm 60`. Multi-color needs a textured task
(an image run with `--multicolor`, or a text run's `texture` step), not an untextured preview.

## 4. Run it

Same command without `--dry-run`. Generation takes minutes, so run it with a long Bash timeout
(up to 600000 ms) or in the background. Output goes to `output/<timestamp>-<slug>/`:
`raw.glb`, `repaired.glb` (if repaired), `model.stl`, `model.3mf`, `preview.png`, `thumbnail.png`,
`manifest.json` (task ids, printability verdicts, credits used), plus `multicolor.3mf` and
`parts/` when requested. Progress goes to stderr; stdout is the final JSON summary.

If the run dies after the generation task was created, don't regenerate (that pays again). Resume with
the task id from the printed log or `manifest.json`: `--resume-task <id>`. Meshy keeps assets for
3 days only.

## 5. Review before handing over

- **Look at `preview.png`** (Read it). The model must stand upright with its base on the red build-plate
  line. If it's lying down or upside down, re-run the local prep on the downloaded GLB, no credits needed:
  `python -m meshy3d prep output/<dir>/raw.glb --height-mm 60 --up z` (or `--up y`), then Read the new preview.
- With `--split`, also Read `parts/preview.png`; with `--multicolor`, Read `multicolor-preview.png`
  if one was made (the preview is best-effort and has no colors).
- Check `mesh_report.warnings` (not watertight, multiple bodies, under 1 mm) and the Meshy verdict in
  `manifest.json` (`healthy` / `warning` / `error` / `unknown`). Report them plainly; don't call a model
  print-ready if it isn't watertight.
- Supports, infill and wall settings stay in the user's slicer.

## 6. Deliver

Give the user the STL/3MF paths, final dimensions, verdict, warnings, and credits consumed. `output/` is
gitignored; in a Claude Code cloud session the container is temporary, so send the STL/3MF/preview files
to the user directly rather than leaving them on disk.
