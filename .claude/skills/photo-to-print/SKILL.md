---
name: photo-to-print
description: Turn a user's photo into a 3D-printable object with Meshy, either a faithful 3D model of the subject (image-to-3D) or a Creative Lab preset (keychain, fridge magnet, figure, vinyl figure, brick figure, lamp, keycap, pixel fidget, collapsible fidget). Use when the user shares or points to a photo and wants something printed from it.
---

# Photo -> printable object

## 1. Get the photo onto disk

The pipeline needs a local .png/.jpg/.jpeg (presets also take .webp) or a public http(s) URL.
- If the user gave a path or URL, use it.
- If they attached an image in chat, check whether it exists as a file you can read (look for an
  uploads path in the message, or search the working directory and home directory for recent image
  files). If you can see the image but can't find a file, say so and ask them to commit it to the repo
  or share a public URL. Don't claim to have the file before you've found it.
- Look at the photo yourself (Read it) before choosing a route: subject, background clutter, lighting.

## 2. Pick the route with the user

Ask what they want if it isn't clear; these give very different objects:

| They want | Route | Credits |
| --- | --- | --- |
| A 3D replica of the subject (statue/figurine of the thing itself) | `/print-model` image mode: `python -m meshy3d image <photo> --height-mm N` | 20 (5 with `--model meshy-6-lite`), +10 if repaired |
| Same, in several filament colors | add `--multicolor` | +20 |
| Keychain medallion (relief, can engrave a name) | preset `keychain` | 6 + 30 |
| Fridge magnet (relief, flat back) | preset `fridge-magnet` | 6 + 30 |
| Cute figurine | preset `figure` (chibi), `vinyl-figure` (big head), `brick-figure` (minifig) | 6 + 30 |
| Lampshade with fixture base | preset `lamp` | 30 + 6 |
| Mechanical keyboard keycap | preset `keycap` | 12 + 50 |
| Pixel-art fidget board, multi-color | preset `fidget-pixel` | 6 + 30 |
| Print-in-place collapsible fidget | preset `fidget-collapsible` | 6 |

`python -m meshy3d preset list` prints the same table with doc links. Prices are from Meshy's pricing
page (checked 2026-10-05); confirm with `python -m meshy3d balance` and a `--dry-run`, and get the
user's OK before spending.

Photo tips (general practice, not Meshy guarantees): one clear subject, plain background, even light,
the whole subject in frame. The collapsible fidget docs specifically warn that busy backgrounds,
several subjects, or very thin shapes can make the task fail.

## 2b. Improve or extend the photos (optional)

- **Clean up** a photo (hand, background, clutter): `python -m meshy3d edit-image photo.jpg --extra "<what it is>"`
  (one task per photo; compare each result with its original before using it).
- **Missing angles** (only front shots): `python -m meshy3d generate-image "the same object from the front,
  side and back, plain white background" --ref photo1.jpg --ref photo2.jpg --multi-view`. Then
  `python -m meshy3d multi-image --from-image-task <id> ...`. These views are AI-invented; check them against
  the real object with the user.
- **Combine references** (e.g. a shape from one photo, colors/label from another): up to 5 `--ref` images and a
  prompt that says what to take from each.
Every image step is paid (3-12 credits per image; multi-view billing isn't documented, so estimates show a
1-3x range). Dry-run first and confirm.

## 3. Presets: prototype, review, then build

Two-stage presets bill each stage separately. **Always stop after the prototype and show the concept.**

```bash
python -m meshy3d preset prototype keychain photo.jpg --param name_text=Luna --dry-run
python -m meshy3d preset prototype keychain photo.jpg --param name_text=Luna
```

Read every `concept-N.png` in the output directory and show/describe it to the user. If they don't like
it, a new prototype costs only the prototype price. When they approve:

```bash
python -m meshy3d preset build keychain --dir output/<dir> --option size_mm=45 --option badge_shape=hexagon
```

Preset-specific inputs (full option lists are on each preset's docs page, linked in `preset list`):
- `keychain`: prototype `name_text` (max 10 chars, engraved). Build options: `size_mm` (default 40),
  `badge_shape` circle|rounded-rect|hexagon|shield|star, `relief_height_mm`, `base_thickness_mm`, ...
- `fridge-magnet`: build `size_mm` (default 60), `base_thickness_mm` (default 2.0), `badge_shape`, ...
- `figure` / `vinyl-figure` / `brick-figure`: no options; Meshy doesn't size them, so the build needs
  `--height-mm` (or `--longest-mm`). These come back textured, so `--multicolor` works here.
- `lamp`: prototype `image_subject` character|landscape. Build `diameter_mm` (default 150),
  `light_source_preset` bambu_mh001_60mm|none, ... Output is Meshy's own STL(s).
- `keycap`: build picks the first design candidate unless `--candidate <id>`; `head_size_mm` 10-40.
- `fidget-pixel`: prototype `type` person|other is **required**. Build `grid_size` 16|32,
  `piece_size_mm` 6|8|10, `color_count` 1-8. Output is Meshy's multi-color 3MF.
- `fidget-collapsible`: single stage, no options: `python -m meshy3d preset run fidget-collapsible photo.jpg`.

Values in `--param`/`--option` are parsed as JSON when possible (`size_mm=45` is a number,
`has_closed_back=false` a boolean); everything else is a string.

## 4. Review and deliver

- Read `preview.png` (or `<name>-preview.png` for Meshy-made STL/3MF). Reliefs should lie flat with
  the relief facing up. If one is upside down, re-run the free local prep with `--flip`:
  `python -m meshy3d prep output/<dir>/model.glb --longest-mm 45 --up flat --flip`.
- Report the sizes from `mesh_report` / `measured`, any warnings, the notes, and `credits_consumed`
  from `manifest.json`. Files Meshy produced directly (lamp, pixel fidget, collapsible fidget,
  multi-color 3MF) are not rescaled; say so.
- In a cloud session, send the STL/3MF and preview to the user; `output/` is temporary and gitignored.
