"""Building primitives shared by the towns: terrain, paths, trees, walls, roofs, doors, signs, buttons.

Conventions: `gy` is the y of the top ground block (players stand at gy + 1). Boxes are inclusive.
Anything the behavior pack script needs (signs, buttons, regions, encounter grass) goes into world.meta.
"""

from __future__ import annotations

from kanto.blocks import AIR, B
from kanto.world import MIN_Y, World

GRASS, DIRT, BEDROCK = B("grass_block"), B("dirt"), B("bedrock")
PATH = B("grass_path")
LIGHT = B("light_block_15")  # invisible light source for ceilings
BARRIER = B("barrier")

# Directions as (dx, dz). Sign/button/arrow encodings for each are kept here so they can be flipped in one
# place if a test in game shows one mirrored.
N, S, W, E = (0, -1), (0, 1), (-1, 0), (1, 0)
FACING = {N: 2, S: 3, W: 4, E: 5}           # facing_direction: wall signs, buttons, glazed terracotta
GROUND_SIGN = {S: 0, W: 4, N: 8, E: 12}     # standing_sign ground_sign_direction: side the text faces
CARDINAL = {N: "north", S: "south", W: "west", E: "east"}


def terrain(w: World, x0, z0, x1, z1, gy, top=GRASS) -> None:
    w.fill(x0, MIN_Y, z0, x1, MIN_Y, z1, BEDROCK)
    if gy - 1 > MIN_Y:
        w.fill(x0, MIN_Y + 1, z0, x1, gy - 1, z1, DIRT)
    w.fill(x0, gy, z0, x1, gy, z1, top)
    w.fill(x0, gy + 1, z0, x1, gy + 40, z1, AIR)
    for x in range(min(x0, x1), max(x0, x1) + 1):
        for z in range(min(z0, z1), max(z0, z1) + 1):
            w.ground[(x, z)] = gy


def path(w: World, x0, z0, x1, z1, gy, b=PATH) -> None:
    w.fill(x0, gy, z0, x1, gy, z1, b)


def leaves(kind="oak"):
    return B(f"{kind}_leaves", persistent_bit=1)


def tree(w: World, x, z, gy, kind="oak", trunk=4) -> None:
    """Small round tree, 3x3 canopy core with a 5x5 skirt."""
    lv = leaves(kind)
    top = gy + trunk
    w.fill(x - 2, top - 1, z - 2, x + 2, top, z + 2, lv)
    for cx, cz in ((x - 2, z - 2), (x + 2, z - 2), (x - 2, z + 2), (x + 2, z + 2)):
        w.set(cx, top, cz, AIR)
    w.fill(x - 1, top + 1, z - 1, x + 1, top + 1, z + 1, lv)
    w.set(x, top + 2, z, lv)
    w.fill(x, gy + 1, z, x, top, z, B(f"{kind}_log"))


def tree_wall(w: World, x0, z0, x1, z1, gy, kind="oak") -> None:
    """Impassable hedge of trees: leaves from the ground up (too tall to jump), trunks showing every 3 blocks."""
    x0, x1 = sorted((x0, x1))
    z0, z1 = sorted((z0, z1))
    lv = leaves(kind)
    w.fill(x0, gy + 1, z0, x1, gy + 6, z1, lv)
    log = B(f"{kind}_log")
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            if (x + 2 * z) % 3 == 0:
                w.fill(x, gy + 1, z, x, gy + 5, z, log)
    w.fill(x0, gy + 7, z0, x1, gy + 7, z1, lv)


def walls(w: World, x0, z0, x1, z1, y0, y1, b) -> None:
    w.fill(x0, y0, z0, x1, y1, z0, b)
    w.fill(x0, y0, z1, x1, y1, z1, b)
    w.fill(x0, y0, z0, x0, y1, z1, b)
    w.fill(x1, y0, z0, x1, y1, z1, b)


def shell(w: World, x0, z0, x1, z1, gy, height, wall, floor, ceiling=None) -> None:
    """Hollow room: floor at gy, walls gy+1..gy+height, ceiling on top, lights in the ceiling."""
    w.fill(x0, gy, z0, x1, gy, z1, floor)
    w.fill(x0 + 1, gy + 1, z0 + 1, x1 - 1, gy + height, z1 - 1, AIR)
    walls(w, x0, z0, x1, z1, gy + 1, gy + height, wall)
    w.fill(x0, gy + height + 1, z0, x1, gy + height + 1, z1, ceiling or wall)
    for x in range(x0 + 3, x1 - 1, 5):
        for z in range(z0 + 3, z1 - 1, 5):
            w.set(x, gy + height, z, LIGHT)


def windows(w: World, x0, z0, x1, z1, y0, y1, side, every=4, width=2, pane=None) -> None:
    """Glass panes along one wall side ('N','S','W','E'), skipping the corners."""
    pane = pane or B("glass")  # full blocks: pane connection states also changed in 1.26.50
    if side in "NS":
        z = z0 if side == "N" else z1
        for x in range(x0 + 2, x1 - 1, every):
            w.fill(x, y0, z, min(x + width - 1, x1 - 2), y1, z, pane)
    else:
        x = x0 if side == "W" else x1
        for z in range(z0 + 2, z1 - 1, every):
            w.fill(x, y0, z, x, y1, min(z + width - 1, z1 - 2), pane)


def door(w: World, x, z, gy, facing, kind="wooden_door") -> None:
    """Two-block door in a wall; `facing` is the outward direction of the wall it sits in."""
    d = CARDINAL[facing]
    w.set(x, gy + 1, z, B(kind, **{"minecraft:cardinal_direction": d, "upper_block_bit": 0}))
    w.set(x, gy + 2, z, B(kind, **{"minecraft:cardinal_direction": d, "upper_block_bit": 1}))


def slab_gable_roof(w: World, x0, z0, x1, z1, y, slab: str, full: str, gable=None) -> None:
    """Gable roof with an east-west ridge, rising half a block per block inward (slabs), one block overhang.

    Under each slab the roof is filled solid down to y, and the gable ends are closed with `gable`.
    """
    lo, hi = z0 - 1, z1 + 1
    k = 0
    while lo + k <= hi - k:
        h = y + k // 2
        top = k % 2 == 1
        for z in {lo + k, hi - k}:
            w.fill(x0 - 1, h, z, x1 + 1, h, z, B(slab, **{"minecraft:vertical_half": "top" if top else "bottom"}))
            if h - 1 >= y:
                w.fill(x0, y, z, x1, h - 1, z, B(full))
        k += 1
    if gable:
        w.fill(x0, y, z0, x0, y, z1, B(gable))
        w.fill(x1, y, z0, x1, y, z1, B(gable))


def flat_roof(w: World, x0, z0, x1, z1, y, top, rim) -> None:
    """Flat colored roof with a raised rim (the look of the Pokemon Center and Mart roofs from above)."""
    w.fill(x0 - 1, y, z0 - 1, x1 + 1, y, z1 + 1, B(top))
    walls(w, x0 - 1, z0 - 1, x1 + 1, z1 + 1, y + 1, y + 1, B(rim))


def sign(w: World, x, y, z, text: str, faces=S, wall=False) -> None:
    """Sign with waxed (uneditable) text. Standing sign by default; wall=True hangs it on the block behind."""
    if wall:
        w.set(x, y, z, B("wall_sign", facing_direction=FACING[faces]))
    else:
        w.set(x, y, z, B("standing_sign", ground_sign_direction=GROUND_SIGN[faces]))
    side = {"Text": text, "TextOwner": "", "SignTextColor": -16777216, "IgnoreLighting": False,
            "PersistFormatting": True}
    w.block_entity(x, y, z, "Sign", FrontText=side, BackText={**side, "Text": ""}, IsWaxed=True)
    w.add_meta("signs", {"p": [x, y, z], "t": text})


def button(w: World, x, y, z, action: str, **args) -> None:
    """Stone button on top of the block below, wired to a script action (see ACTIONS in the pack's main.js)."""
    w.set(x, y, z, B("stone_button", facing_direction=1))
    w.add_meta("buttons", {"p": [x, y, z], "a": action, **args})


def region(w: World, name: str, x0, z0, x1, z1, sub: str = "", building=False) -> None:
    x0, x1 = sorted((x0, x1))
    z0, z1 = sorted((z0, z1))
    w.add_meta("regions", {"n": name, "s": sub, "b": [x0, z0, x1, z1], "in": building})


def tall_grass(w: World, x0, z0, x1, z1, gy, wild: list[str], area: str) -> None:
    """Patch of tall grass where wild Pokemon 'appear' (an on-screen message from the script)."""
    w.fill(x0, gy + 1, z0, x1, gy + 1, z1, B("short_grass"))
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            if (x * 7 + z * 13) % 5 == 0:
                w.set(x, gy + 1, z, B("tall_grass", upper_block_bit=0))
                w.set(x, gy + 2, z, B("tall_grass", upper_block_bit=1))
    w.add_meta("grass", {"b": [min(x0, x1), min(z0, z1), max(x0, x1), max(z0, z1)], "y": gy + 1,
                         "w": wild, "area": area})


def flowers(w: World, x0, z0, x1, z1, gy, kinds=("poppy", "dandelion", "oxeye_daisy", "cornflower")) -> None:
    i = 0
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            if (x + z) % 2 == 0:
                w.set(x, gy + 1, z, B(kinds[i % len(kinds)]))
                i += 1


def wall_line(w: World, x0, z0, x1, z1, gy, kind="cobblestone_wall") -> None:
    """Straight low wall (1.5 blocks: too tall to jump), connected to any wall blocks already beside it.

    Walls rather than fences: 1.26.50 added fence connection states that the 26.40 block data can't set,
    while wall connections are explicit states here.
    """
    cells = {(x, z) for x in range(min(x0, x1), max(x0, x1) + 1) for z in range(min(z0, z1), max(z0, z1) + 1)}
    y = gy + 1
    cells |= {(x + dx, z + dz) for x, z in cells for dx, dz in (N, S, W, E)
              if w.get(x + dx, y, z + dz).name == kind}
    def is_wall(x, z):
        return (x, z) in cells or w.get(x, y, z).name == kind

    for x, z in cells:
        conn = {d: is_wall(x + v[0], z + v[1]) for d, v in (("north", N), ("south", S), ("west", W), ("east", E))}
        straight = (conn["north"] and conn["south"] and not conn["east"] and not conn["west"]) or (
            conn["east"] and conn["west"] and not conn["north"] and not conn["south"])
        w.set(x, y, z, B(kind, wall_post_bit=0 if straight else 1,
                         **{f"wall_connection_type_{d}": "short" if c else "none" for d, c in conn.items()}))


def pixel_art(w: World, x0, y_top, z, rows: list[str], colors: dict[str, str], along=E) -> None:
    """Wall pixel art in a vertical plane: rows top to bottom, characters along `along` from x0."""
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch in colors:
                w.set(x0 + c * along[0], y_top - r, z + c * along[1], B(colors[ch]))
