"""Enterable buildings. Each takes the north-west corner (x0, z0) and ground y and faces its door south,
the way the towns are laid out in FireRed/LeafGreen (north is up on the map, -z in game).
"""

from __future__ import annotations

from kanto import gym_puzzle
from kanto.blocks import AIR, B
from kanto.build import (
    FACING,
    LIGHT,
    E,
    N,
    S,
    W,
    button,
    door,
    flat_roof,
    pixel_art,
    region,
    shell,
    sign,
    slab_gable_roof,
    windows,
)
from kanto.world import World

POKEBALL = [".KKKKK.", "KRRRRRK", "KRRRRRK", "KKKWKKK", "KWWWWWK", "KWWWWWK", ".KKKKK."]
BALL_COLORS = {"K": "black_concrete", "R": "red_concrete", "W": "white_concrete"}
ARROW = B("magenta_glazed_terracotta")
# facing_direction that makes the arrow printed on the tile point each way. Assumed to match FACING; if the
# arrows show up mirrored in game, swap N/S and W/E here (the sliding itself uses the grid, not the tile).
ARROW_FACING = dict(FACING)


def _bed(w: World, x, y, z, head=N, color=14) -> None:
    """Two-block bed, foot at (x, z), head one block toward `head`."""
    d = {S: 0, W: 1, N: 2, E: 3}[head]
    hx, hz = x + head[0], z + head[1]
    w.set(x, y, z, B("bed", direction=d, head_piece_bit=0))
    w.set(hx, y, hz, B("bed", direction=d, head_piece_bit=1))
    for px, pz in ((x, z), (hx, hz)):
        w.block_entity(px, y, pz, "Bed", color=color)


def _table(w: World, x, y, z) -> None:
    w.set(x, y, z, B("oak_fence"))
    w.set(x, y + 1, z, B("wooden_pressure_plate"))


def pokemon_center(w: World, x0, z0, gy, town: str) -> None:
    x1, z1 = x0 + 22, z0 + 16
    mid = x0 + 11
    shell(w, x0, z0, x1, z1, gy, 8, B("white_concrete"), B("smooth_quartz"))
    w.fill(x0, gy + 7, z0, x1, gy + 8, z0, B("red_concrete"))
    w.fill(x0, gy + 7, z1, x1, gy + 8, z1, B("red_concrete"))
    w.fill(x0, gy + 7, z0, x0, gy + 8, z1, B("red_concrete"))
    w.fill(x1, gy + 7, z0, x1, gy + 8, z1, B("red_concrete"))
    flat_roof(w, x0, z0, x1, z1, gy + 9, "red_concrete", "red_concrete")
    windows(w, x0, z0, x1, z1, gy + 2, gy + 4, "W")
    windows(w, x0, z0, x1, z1, gy + 2, gy + 4, "E")
    w.fill(x0 + 3, gy + 2, z1, x0 + 7, gy + 4, z1, B("glass"))
    w.fill(x1 - 7, gy + 2, z1, x1 - 3, gy + 4, z1, B("glass"))
    # glass entrance (always open, like the automatic doors) under a Poke Ball sign board
    w.fill(mid - 1, gy + 1, z1, mid + 1, gy + 3, z1, AIR)
    w.fill(mid - 4, gy + 4, z1 + 1, mid + 4, gy + 12, z1 + 1, B("white_concrete"))
    pixel_art(w, mid - 3, gy + 11, z1 + 1, POKEBALL, BALL_COLORS)
    sign(w, mid, gy + 4, z1 + 2, f"{town}\nPOKéMON CENTER", faces=S, wall=True)
    # counter across the room; nurse area and healing machine behind it
    w.fill(x0 + 1, gy + 1, z0 + 5, x1 - 1, gy + 1, z0 + 5, B("red_concrete"))
    w.fill(x0 + 1, gy + 1, z0 + 4, x1 - 1, gy + 1, z0 + 4, B("quartz_block"))
    w.fill(mid - 3, gy + 1, z0 + 1, mid + 3, gy + 1, z0 + 1, B("iron_block"))
    for i, x in enumerate(range(mid - 2, mid + 3)):
        w.set(x, gy + 2, z0 + 1, B("red_concrete" if i % 2 == 0 else "white_concrete"))
    w.set(mid, gy + 3, z0 + 1, B("sea_lantern"))
    w.set(mid - 2, gy + 1, z0 + 3, B("pink_wool"))  # Chansey-pink stool behind the counter
    button(w, mid, gy + 2, z0 + 5, "heal")
    sign(w, mid - 2, gy + 2, z0 + 5, "NURSE JOY:\nWelcome! Press\nthe button to\nheal POKéMON!")
    # PC corner, benches, plants, carpet runner
    w.set(x1 - 2, gy + 1, z0 + 7, B("light_gray_concrete"))
    w.set(x1 - 2, gy + 2, z0 + 7, B("black_concrete"))
    sign(w, x1 - 3, gy + 1, z0 + 7, "POKéMON\nSTORAGE PC\n(coming soon)", faces=W)
    for z in (z0 + 8, z0 + 11):
        w.fill(x0 + 2, gy + 1, z, x0 + 6, gy + 1, z, B("oak_slab"))
    for x, z in ((x0 + 1, z1 - 1), (x1 - 1, z1 - 1), (x0 + 1, z0 + 6), (x1 - 1, z0 + 6)):
        w.set(x, gy + 1, z, B("flowering_azalea"))
    w.fill(mid - 1, gy + 1, z0 + 6, mid + 1, gy + 1, z1 - 1, B("red_carpet"))
    region(w, f"{town} POKéMON CENTER", x0, z0, x1, z1, building=True)


def poke_mart(w: World, x0, z0, gy, town: str) -> None:
    x1, z1 = x0 + 16, z0 + 12
    mid = x0 + 8
    shell(w, x0, z0, x1, z1, gy, 6, B("white_concrete"), B("smooth_stone"))
    for z in (z0, z1):
        w.fill(x0, gy + 5, z, x1, gy + 6, z, B("blue_concrete"))
    for x in (x0, x1):
        w.fill(x, gy + 5, z0, x, gy + 6, z1, B("blue_concrete"))
    flat_roof(w, x0, z0, x1, z1, gy + 7, "blue_concrete", "light_blue_concrete")
    windows(w, x0, z0, x1, z1, gy + 2, gy + 3, "E")
    w.fill(x1 - 6, gy + 2, z1, x1 - 2, gy + 3, z1, B("glass"))
    w.fill(mid - 1, gy + 1, z1, mid + 1, gy + 3, z1, AIR)
    w.fill(mid - 3, gy + 4, z1 + 1, mid + 3, gy + 7, z1 + 1, B("blue_concrete"))
    sign(w, mid, gy + 5, z1 + 2, "POKé MART", faces=S, wall=True)
    # counter on the west side with a button for each item
    cx = x0 + 4
    w.fill(cx, gy + 1, z0 + 5, cx, gy + 1, z0 + 11, B("oak_planks"))
    w.fill(x0 + 1, gy + 1, z0 + 4, cx, gy + 1, z0 + 4, B("oak_planks"))
    sign(w, cx, gy + 2, z0 + 5, "POKé BALL\nPress the\nbutton below!", faces=E)
    button(w, cx, gy + 2, z0 + 6, "give", item="poke_ball")
    sign(w, cx, gy + 2, z0 + 8, "CLERK:\nWelcome! Help\nyourself, it's\nfree today!", faces=E)
    button(w, cx, gy + 2, z0 + 10, "give", item="potion")
    sign(w, cx, gy + 2, z0 + 11, "POTION\nPress the\nbutton above!", faces=E)
    w.set(x0 + 2, gy + 1, z0 + 7, B("light_blue_wool"))  # the clerk's stool
    for z in (z0 + 2, z0 + 5, z0 + 8):
        w.fill(x0 + 8, gy + 1, z, x1 - 2, gy + 2, z, B("bookshelf"))
    w.fill(mid - 1, gy + 1, z1 - 1, mid + 1, gy + 1, z1 - 1, B("blue_carpet"))
    region(w, f"{town} POKé MART", x0, z0, x1, z1, building=True)


def gym(w: World, x0, z0, gy, town: str, leader: str, badge: str, gtype: str) -> None:
    """Gym with the spinner-tile maze between the entrance lobby and the leader's platform."""
    x1, z1 = x0 + 34, z0 + 40
    mid = x0 + 17
    H = 7
    shell(w, x0, z0, x1, z1, gy, H, B("stone_bricks"), B("polished_andesite"), B("smooth_stone"))
    w.fill(x0, gy + H - 1, z1, x1, gy + H, z1, B("orange_terracotta"))
    flat_roof(w, x0, z0, x1, z1, gy + H + 1, "orange_terracotta", "brick_block")
    windows(w, x0, z0, x1, z1, gy + 4, gy + 5, "W", every=6)
    windows(w, x0, z0, x1, z1, gy + 4, gy + 5, "E", every=6)
    w.fill(mid - 1, gy + 1, z1, mid + 1, gy + 3, z1, AIR)
    w.fill(mid - 5, gy + 4, z1 + 1, mid + 5, gy + H + 3, z1 + 1, B("brick_block"))
    sign(w, mid, gy + 5, z1 + 2, f"{town}\nPOKéMON GYM", faces=S, wall=True)
    # maze: 31 columns from x0+2, rows from z0+6; the strip inside each side wall is solid
    grid = gym_puzzle.layout()
    mx, mz = x0 + 2, z0 + 6
    w.fill(x0 + 1, gy + 1, mz, x0 + 1, gy + H, mz + gym_puzzle.ROWS - 4, B("stone_bricks"))
    w.fill(x1 - 1, gy + 1, mz, x1 - 1, gy + H, mz + gym_puzzle.ROWS - 4, B("stone_bricks"))
    floor = {".": B("smooth_sandstone"), "G": B("smooth_sandstone")}
    arrows = {"^": N, "v": S, "<": W, ">": E}
    for r, row in enumerate(grid):
        for c, ch in enumerate(row):
            x, z = mx + c, mz + r
            if ch == "#":
                w.fill(x, gy, z, x, gy + H, z, B("stone_bricks"))
            elif ch in arrows:
                w.set(x, gy, z, ARROW.with_(facing_direction=ARROW_FACING[arrows[ch]]))
            else:
                w.set(x, gy, z, floor[ch])
    w.add_meta("spinners", {"o": [mx, mz], "y": gy, "g": grid})
    # leader's platform
    w.fill(x0 + 1, gy, z0 + 1, x1 - 1, gy, mz - 1, B("polished_granite"))
    w.fill(mid - 2, gy + 1, z0 + 1, mid + 2, gy + 1, mz - 1, B("red_carpet"))
    w.set(mid, gy + 1, z0 + 2, B("gold_block"))
    button(w, mid, gy + 2, z0 + 2, "badge", badge=badge, leader=leader)
    sign(w, mid - 2, gy + 1, z0 + 2, f"{leader}:\nYou made it!\nPress the gold\nbutton!", faces=S)
    for x in (x0 + 3, x1 - 3):
        w.fill(x, gy + 1, z0 + 2, x, gy + 3, z0 + 2, B("polished_andesite"))
        w.set(x, gy + 4, z0 + 2, B("lantern"))
    # entrance lobby: statues and the guide
    for x in (mid - 4, mid + 4):
        w.fill(x, gy + 1, z1 - 3, x, gy + 2, z1 - 3, B("polished_andesite"))
        w.set(x, gy + 3, z1 - 3, B("gold_block"))
    sign(w, mid - 3, gy + 1, z1 - 2, f"{town} GYM\nLEADER:\n{leader}\n{gtype} type", faces=S)
    sign(w, mid + 3, gy + 1, z1 - 2, "GYM GUIDE:\nArrow tiles\npush you! Find\nthe way up!", faces=S)
    region(w, f"{town} GYM", x0, z0, x1, z1, sub=f"Leader: {leader}", building=True)


def house(w: World, x0, z0, gy, name: str, wall="oak_planks", roof=("dark_oak_slab", "dark_oak_planks"),
          door_dx=5, two_floors=False, label: str | None = None) -> tuple[int, int, int, int]:
    """13x11 house with a slab gable roof and a door in the south wall. Returns the 1F interior box."""
    x1, z1 = x0 + 12, z0 + 10
    h1 = 4
    total = h1 * 2 + 1 if two_floors else h1
    shell(w, x0, z0, x1, z1, gy, total, B(wall), B("spruce_planks"))
    w.fill(x0, gy + 1, z0, x0, gy + total, z0, B("stripped_oak_log"))
    for x, z in ((x1, z0), (x0, z1), (x1, z1)):
        w.fill(x, gy + 1, z, x, gy + total, z, B("stripped_oak_log"))
    windows(w, x0, z0, x1, z1, gy + 2, gy + 3, "S", every=6)
    windows(w, x0, z0, x1, z1, gy + 2, gy + 3, "W", every=5)
    windows(w, x0, z0, x1, z1, gy + 2, gy + 3, "E", every=5)
    dx = x0 + door_dx
    door(w, dx, z1, gy, S)
    if two_floors:
        fy = gy + h1 + 1  # second floor block
        w.fill(x0 + 1, fy, z0 + 1, x1 - 1, fy, z1 - 1, B("spruce_planks"))
        for x in range(x0 + 3, x1 - 1, 5):
            for z in range(z0 + 3, z1 - 1, 5):
                w.set(x, fy - 1, z, LIGHT)
        windows(w, x0, z0, x1, z1, fy + 2, fy + 3, "S", every=6)
        windows(w, x0, z0, x1, z1, fy + 2, fy + 3, "W", every=5)
        # staircase up the east wall, climbing north, two wide
        for i in range(h1 + 1):
            z = z1 - 3 - i
            if z < z0 + 2:
                break
            for x in (x1 - 2, x1 - 1):
                if i:
                    w.fill(x, gy + 1, z, x, gy + i, z, B("oak_planks"))
                w.set(x, gy + 1 + i, z, B("oak_stairs", weirdo_direction=3))
                if 1 <= i < h1:  # headroom over the lower steps; the top step sits in the floor
                    w.set(x, fy, z, AIR)
        w.fill(x1 - 3, fy + 1, z1 - 3 - h1, x1 - 3, fy + 1, z1 - 4, B("oak_fence"))
    slab_gable_roof(w, x0, z0, x1, z1, gy + total + 1, roof[0], roof[1], gable=wall)
    sign(w, dx - 2, gy + 1, z1 + 2, label or name, faces=S)
    region(w, name, x0, z0, x1, z1, building=True)
    return x0 + 1, z0 + 1, x1 - 1, z1 - 1


def player_house(w: World, x0, z0, gy) -> None:
    ix0, iz0, _, iz1 = house(w, x0, z0, gy, "YOUR HOUSE", wall="white_terracotta",
                               roof=("mangrove_slab", "mangrove_planks"), two_floors=True)
    # 1F: kitchen, table, TV, rug
    w.fill(ix0, gy + 1, iz0, ix0 + 3, gy + 1, iz0, B("smooth_stone"))
    w.set(ix0 + 1, gy + 1, iz0, B("furnace", **{"minecraft:cardinal_direction": "south"}))
    w.set(ix0 + 2, gy + 1, iz0, B("cauldron"))
    _table(w, ix0 + 3, gy + 1, iz0 + 4)
    _table(w, ix0 + 4, gy + 1, iz0 + 4)
    w.set(ix0 + 7, gy + 1, iz0, B("spruce_planks"))
    w.set(ix0 + 7, gy + 2, iz0, B("black_concrete"))  # TV
    w.fill(ix0 + 2, gy + 1, iz0 + 6, ix0 + 6, gy + 1, iz0 + 7, B("red_carpet"))
    sign(w, ix0 + 1, gy + 1, iz0 + 3, "MOM:\nHave fun out\nin KANTO!\nCome back soon!")
    # 2F: bed, PC, game console, rug
    fy = gy + 6
    _bed(w, ix0 + 1, fy, iz0 + 1, head=N)
    w.set(ix0 + 4, fy, iz0, B("oak_planks"))
    w.set(ix0 + 4, fy + 1, iz0, B("light_gray_concrete"))  # PC
    sign(w, ix0 + 3, fy, iz0 + 1, "It's your PC!\nYour items are\nsafe in here.")
    w.set(ix0 + 1, fy, iz1, B("black_concrete"))  # TV
    w.set(ix0 + 2, fy, iz1, B("gray_concrete"))   # game console
    w.fill(ix0 + 3, fy, iz0 + 3, ix0 + 6, fy, iz0 + 5, B("blue_carpet"))
    w.set(ix0, fy, iz1, B("flowering_azalea"))


def rival_house(w: World, x0, z0, gy) -> None:
    ix0, iz0, ix1, iz1 = house(w, x0, z0, gy, "BLUE's HOUSE", wall="white_terracotta",
                               roof=("deepslate_tile_slab", "deepslate_tiles"), door_dx=7)
    _table(w, ix0 + 5, gy + 1, iz0 + 4)
    _table(w, ix0 + 6, gy + 1, iz0 + 4)
    w.fill(ix0, gy + 1, iz0, ix0 + 1, gy + 2, iz0, B("bookshelf"))
    w.fill(ix1 - 1, gy + 1, iz0, ix1, gy + 2, iz0, B("bookshelf"))
    w.set(ix1, gy + 1, iz1, B("flowering_azalea"))
    sign(w, ix0 + 3, gy + 1, iz0 + 3, "DAISY:\nGrandpa is at\nhis LAB, just\nsouth of here!")
    w.fill(ix0 + 3, gy + 1, iz0 + 6, ix0 + 8, gy + 1, iz0 + 7, B("yellow_carpet"))


def oak_lab(w: World, x0, z0, gy) -> None:
    x1, z1 = x0 + 22, z0 + 14
    mid = x0 + 11
    shell(w, x0, z0, x1, z1, gy, 6, B("white_concrete"), B("smooth_stone"))
    windows(w, x0, z0, x1, z1, gy + 2, gy + 4, "S", every=5)
    windows(w, x0, z0, x1, z1, gy + 2, gy + 4, "W", every=4)
    windows(w, x0, z0, x1, z1, gy + 2, gy + 4, "E", every=4)
    door(w, mid, z1, gy, S)
    slab_gable_roof(w, x0, z0, x1, z1, gy + 7, "deepslate_tile_slab", "deepslate_tiles", gable="white_concrete")
    # bookshelves along the back wall and down the sides, machines in the corners
    w.fill(x0 + 1, gy + 1, z0 + 1, x0 + 7, gy + 3, z0 + 1, B("bookshelf"))
    w.fill(x1 - 7, gy + 1, z0 + 1, x1 - 1, gy + 3, z0 + 1, B("bookshelf"))
    for z in (z0 + 7, z0 + 10):
        w.fill(x0 + 2, gy + 1, z, x0 + 6, gy + 2, z, B("bookshelf"))
        w.fill(x1 - 6, gy + 1, z, x1 - 2, gy + 2, z, B("bookshelf"))
    for x in (x0 + 1, x1 - 1):
        w.fill(x, gy + 1, z0 + 3, x, gy + 2, z0 + 4, B("iron_block"))
        w.set(x, gy + 3, z0 + 3, B("sea_lantern"))
    # the table with three Poke Balls (red mushroom blocks look the part) and a button on each
    w.fill(mid - 3, gy + 1, z0 + 3, mid + 3, gy + 1, z0 + 3, B("smooth_quartz"))
    starters = [("BULBASAUR", "GRASS"), ("CHARMANDER", "FIRE"), ("SQUIRTLE", "WATER")]
    for (name, kind), x in zip(starters, (mid - 2, mid, mid + 2)):
        w.set(x, gy + 2, z0 + 3, B("red_mushroom_block", huge_mushroom_bits=14))
        button(w, x, gy + 3, z0 + 3, "starter", pokemon=name)
        sign(w, x, gy + 1, z0 + 4, f"{name}\n{kind} type\nPress the\nbutton on top!")
    sign(w, mid - 4, gy + 1, z0 + 5, "PROF. OAK:\nChoose your\nfirst POKéMON!")
    w.fill(mid - 1, gy + 1, z0 + 6, mid + 1, gy + 1, z1 - 1, B("green_carpet"))
    sign(w, mid + 3, gy + 1, z1 + 2, "OAK POKéMON\nRESEARCH LAB", faces=S)
    region(w, "PROF. OAK's LAB", x0, z0, x1, z1, building=True)


def trainer_school(w: World, x0, z0, gy) -> None:
    x1, z1 = x0 + 14, z0 + 10
    mid = x0 + 7
    shell(w, x0, z0, x1, z1, gy, 5, B("brick_block"), B("oak_planks"))
    windows(w, x0, z0, x1, z1, gy + 2, gy + 3, "W", every=4)
    windows(w, x0, z0, x1, z1, gy + 2, gy + 3, "E", every=4)
    door(w, mid, z1, gy, S)
    slab_gable_roof(w, x0, z0, x1, z1, gy + 6, "spruce_slab", "spruce_planks", gable="brick_block")
    w.fill(x0 + 3, gy + 2, z0 + 1, x1 - 3, gy + 3, z0 + 1, B("black_concrete"))  # blackboard
    for z in (z0 + 4, z0 + 6, z0 + 8):
        for x in (x0 + 3, x0 + 6, x0 + 9, x0 + 12):
            if x < x1:
                _table(w, x, gy + 1, z)
    sign(w, mid, gy + 1, z0 + 2, "TRAINER TIPS:\nPOKéMON CENTERS\nheal your team\nfor free!")
    sign(w, mid + 2, gy + 1, z1 + 2, "TRAINER SCHOOL", faces=S)
    region(w, "TRAINER SCHOOL", x0, z0, x1, z1, building=True)
