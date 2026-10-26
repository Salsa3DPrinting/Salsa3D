"""The map: Pallet Town, Route 1 and Viridian City, laid out like FireRed/LeafGreen (north = -z).

Ground heights step up going north, like the ledges on Route 1: Pallet at y -60, the middle of Route 1 at
-58, the top of Route 1 and Viridian at -56. Ledges are 2-block drops (you can hop down, not climb up);
the path climbs them on slab ramps.
"""

from __future__ import annotations

from kanto import buildings as bld
from kanto.blocks import B
from kanto.build import BARRIER, E, S, flowers, path, region, sign, tall_grass, terrain, tree, tree_wall, wall_line
from kanto.world import World

BASE = -60
PALLET = (0, 0, 79, 63)
ROUTE1 = (16, -128, 63, -1)
VIRIDIAN = (-24, -264, 135, -129)
BOUNDS = (-48, -288, 159, 79)  # whole chunks, all written; outside them the flat generator makes plain grass
SPAWN = (20, BASE + 1, 27)
RAMP_SLAB, RAMP_FULL = "smooth_sandstone_slab", "smooth_sandstone"


def ramp(w: World, x0, x1, z_top_edge, low) -> None:
    """Walkable half-block steps from ground `low` up to `low + 2`; the upper terrace starts at z_top_edge."""
    z = z_top_edge
    w.fill(x0, low + 1, z + 3, x1, low + 1, z + 3, B(RAMP_SLAB))
    w.fill(x0, low + 1, z + 2, x1, low + 1, z + 2, B(RAMP_FULL))
    w.fill(x0, low + 1, z + 1, x1, low + 1, z + 1, B(RAMP_FULL))
    w.fill(x0, low + 2, z + 1, x1, low + 2, z + 1, B(RAMP_SLAB))


def pallet_town(w: World) -> None:
    gy = BASE
    x0, z0, x1, z1 = PALLET
    tree_wall(w, x0, z0, x0 + 3, z1, gy)
    tree_wall(w, x1 - 3, z0, x1, z1, gy)
    tree_wall(w, x0, z1 - 3, x1, z1, gy)
    tree_wall(w, x0, z0, 33, z0 + 3, gy)
    tree_wall(w, 46, z0, x1, z0 + 3, gy)
    # paths: from Route 1 down the middle, branches to both houses and the lab
    path(w, 36, z0, 43, 30, gy)
    path(w, 18, 24, 60, 27, gy)
    path(w, 18, 22, 21, 27, gy)
    path(w, 54, 22, 57, 27, gy)
    path(w, 51, 27, 55, 51, gy)
    bld.player_house(w, 14, 12, gy)
    bld.rival_house(w, 50, 12, gy)
    bld.oak_lab(w, 42, 35, gy)
    # garden with a fence, flowers and the town sign
    flowers(w, 16, 36, 30, 44, gy)
    wall_line(w, 15, 35, 31, 35, gy)
    wall_line(w, 15, 45, 31, 45, gy)
    wall_line(w, 15, 35, 15, 45, gy)
    wall_line(w, 31, 35, 31, 45, gy)
    sign(w, 34, gy + 1, 29, "PALLET TOWN\nShades of your\njourney await!")
    # the sea to the south (Route 21), fenced off with invisible barriers
    w.fill(10, gy - 3, 52, 42, gy - 3, 59, B("sand"))
    w.fill(10, gy - 2, 52, 42, gy, 59, B("water"))
    w.fill(9, gy, 51, 43, gy, 51, B("sand"))
    w.fill(10, gy + 1, 59, 42, gy + 3, 59, BARRIER)
    sign(w, 26, gy + 1, 49, "ROUTE 21\nby the sea\ncoming soon!", faces=S)
    for x, z in ((8, 30), (30, 8), (68, 30), (68, 52), (36, 47)):
        tree(w, x, z, gy)
    region(w, "PALLET TOWN", x0, z0, x1, z1, sub="Shades of your journey await!")


def route_1(w: World) -> None:
    x0, z0, x1, z1 = ROUTE1
    terraces = [(-44, z1, BASE), (-88, -45, BASE + 2), (z0, -89, BASE + 4)]  # (north z, south z, ground)
    for zn, zs, gy in terraces:
        terrain(w, x0, zn, x1, zs, gy)
        tree_wall(w, x0, zn, x0 + 3, zs, gy)
        tree_wall(w, x1 - 3, zn, x1, zs, gy)
    low, mid, high = BASE, BASE + 2, BASE + 4
    # path: weaves north, climbing each ledge on a ramp
    path(w, 36, -20, 43, z1, low)
    path(w, 24, -24, 43, -20, low)
    path(w, 24, -44, 29, -24, low)
    ramp(w, 24, 29, -45, low)
    path(w, 24, -64, 29, -45, mid)
    path(w, 24, -64, 49, -60, mid)
    path(w, 44, -88, 49, -64, mid)
    ramp(w, 44, 49, -89, mid)
    path(w, 36, -104, 49, -89, high)
    path(w, 36, z0, 43, -104, high)
    wild = ["PIDGEY", "RATTATA"]
    tall_grass(w, 44, -40, 56, -26, low, wild, "ROUTE 1")
    tall_grass(w, 20, -18, 30, -6, low, wild, "ROUTE 1")
    tall_grass(w, 32, -84, 42, -68, mid, wild, "ROUTE 1")
    tall_grass(w, 20, -86, 28, -70, mid, wild, "ROUTE 1")
    tall_grass(w, 20, -124, 32, -108, high, wild, "ROUTE 1")
    tall_grass(w, 50, -120, 56, -94, high, wild, "ROUTE 1")
    for x, z, gy in ((32, -36, low), (52, -54, mid), (34, -54, mid), (26, -96, high), (52, -12, low)):
        tree(w, x, z, gy)
    flowers(w, 52, -86, 56, -78, mid)
    sign(w, 34, low + 1, -6, "ROUTE 1\nPALLET TOWN -\nVIRIDIAN CITY")
    sign(w, 31, low + 1, -42, "TIP: Hop down\nthe ledges to\nget home fast!")
    region(w, "ROUTE 1", x0, z0, x1, z1)


def viridian_city(w: World) -> None:
    gy = BASE + 4
    x0, z0, x1, z1 = VIRIDIAN
    terrain(w, x0, z0, x1, z1, gy)
    # borders: open to Route 1 in the south; west (Route 22) and north (Route 2) are fenced for now
    tree_wall(w, x0, z1 - 3, 19, z1, gy)
    tree_wall(w, 60, z1 - 3, x1, z1, gy)
    tree_wall(w, x0, z0, x0 + 3, -206, gy)
    tree_wall(w, x0, -195, x0 + 3, z1, gy)
    tree_wall(w, x1 - 3, z0, x1, z1, gy)
    tree_wall(w, x0, z0, 35, z0 + 3, gy)
    tree_wall(w, 44, z0, x1, z0 + 3, gy)
    wall_line(w, x0 + 1, -205, x0 + 1, -196, gy)
    wall_line(w, 36, z0 + 1, 43, z0 + 1, gy)
    sign(w, x0 + 3, gy + 1, -200, "ROUTE 22\nto the POKéMON\nLEAGUE\ncoming soon!", faces=E)
    sign(w, 40, gy + 1, z0 + 5, "ROUTE 2\nVIRIDIAN FOREST\ncoming soon!", faces=S)
    # streets
    path(w, 36, -178, 43, z1, gy)                # from Route 1
    path(w, x0 + 4, -178, 116, -174, gy)          # main east-west street
    path(w, x0 + 4, -203, x0 + 9, -174, gy)       # to Route 22
    path(w, 36, z0 + 4, 43, -178, gy)            # north to Route 2
    path(w, 77, -213, 81, -178, gy)              # to the gym
    path(w, 106, -182, 110, -178, gy)            # to the mart
    path(w, 18, -152, 58, -148, gy)              # side street past the center and the house
    path(w, 18, -153, 20, -152, gy)
    path(w, -1, -189, 1, -178, gy)               # to the school
    bld.pokemon_center(w, 8, -170, gy, "VIRIDIAN")
    bld.poke_mart(w, 100, -196, gy, "VIRIDIAN")
    bld.gym(w, 62, -254, gy, "VIRIDIAN", "GIOVANNI", "EARTH BADGE", "GROUND")
    bld.trainer_school(w, -8, -200, gy)
    hx0, hz0, _, _ = bld.house(w, 52, -168, gy, "NICKNAME HOUSE", wall="spruce_planks",
                               roof=("brick_slab", "brick_block"))
    sign(w, hx0 + 3, gy + 1, hz0 + 3, "Giving POKéMON\nnicknames makes\nthem feel\nspecial!")
    # pond and greenery
    w.fill(-6, gy - 3, -232, 12, gy - 3, -214, B("sand"))
    w.fill(-6, gy - 2, -232, 12, gy, -214, B("water"))
    for x in (-4, 2, 8):
        w.set(x, gy + 1, -222, B("waterlily"))
    flowers(w, 14, -232, 20, -214, gy)
    for x, z in ((0, -140), (60, -140), (100, -140), (90, -150), (120, -160), (120, -220), (20, -245),
                 (48, -240), (110, -245), (-12, -245)):
        tree(w, x, z, gy)
    sign(w, 34, gy + 1, -140, "VIRIDIAN CITY\nThe eternally\ngreen paradise")
    sign(w, 75, gy + 1, -210, "VIRIDIAN CITY\nPOKéMON GYM\nLEADER:\nGIOVANNI", faces=S)
    region(w, "VIRIDIAN CITY", x0, z0, x1, z1, sub="The eternally green paradise")


def build() -> World:
    w = World()
    bx0, bz0, bx1, bz1 = BOUNDS
    terrain(w, bx0, bz0, bx1, bz1, BASE)
    pallet_town(w)
    route_1(w)
    viridian_city(w)
    w.add_meta("spawn", list(SPAWN))
    return w

