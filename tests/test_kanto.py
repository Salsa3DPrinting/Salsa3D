"""Kanto Minecraft Bedrock world: file formats (NBT, LevelDB log, sub-chunks) and the built map."""

import json
import struct
import zipfile

import numpy as np
import pytest

from kanto import gym_puzzle, leveldb, nbt, places
from kanto.blocks import AIR, SPECS, B
from kanto.level import level_dat
from kanto.world import MIN_Y, World


def decode_subchunk(data: bytes):
    """Inverse of World._subchunk: returns (y index, [16 x][16 z][16 y] palette indices, palette NBT)."""
    assert data[0] == 9 and data[1] == 1
    sy = struct.unpack("<b", data[2:3])[0]
    bits = data[3] >> 1
    assert data[3] & 1 == 0  # persistent palette
    per = 32 // bits
    nwords = -(-4096 // per)
    words = np.frombuffer(data, "<u4", nwords, 4)
    vals = ((words[:, None] >> (np.arange(per, dtype=np.uint32) * bits)) & ((1 << bits) - 1)).ravel()[:4096]
    off = 4 + nwords * 4
    (count,) = struct.unpack_from("<i", data, off)
    off += 4
    palette = []
    for _ in range(count):
        tag, off = nbt.loads(data, off)
        palette.append(tag)
    assert off == len(data)
    return sy, vals.reshape(16, 16, 16), palette


def test_nbt_round_trip():
    v = {"a": nbt.Byte(1), "b": 7, "c": nbt.Long(1 << 40), "d": 1.5, "e": "héllo", "f": nbt.List([1, 2, 3]),
         "g": {"h": nbt.Short(-3)}, "i": nbt.List([], tag=nbt.COMPOUND)}
    out, end = nbt.loads(nbt.dumps(v))
    assert out == v and end == len(nbt.dumps(v))


def test_crc32c_and_log_round_trip(tmp_path):
    assert leveldb.crc32c(b"123456789") == 0xE3069283  # the standard CRC-32C check value
    items = [(f"k{i}".encode(), bytes([i % 256]) * (i * 37 % 70000)) for i in range(60)]  # spans 32 KiB blocks
    assert leveldb.write_db(tmp_path / "db", items) == 60
    assert list(leveldb.read_log(tmp_path / "db")) == items
    assert (tmp_path / "db" / "CURRENT").read_bytes() == b"MANIFEST-000002\n"


@pytest.mark.parametrize("n", [1, 2, 3, 5, 17, 33, 65, 200, 300])
def test_subchunk_encoding_every_bit_width(n):
    w = World()
    colors = ["white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray", "light_gray", "cyan",
              "purple", "blue", "brown", "green", "red", "black"]
    blocks = [B(f"{c}_{k}") for k in ("wool", "concrete", "terracotta", "carpet", "stained_glass") for c in colors]
    blocks += [B("water", liquid_depth=d) for d in range(16)] + [B("oak_log", pillar_axis=a) for a in "xyz"]
    blocks += [B("standing_sign", ground_sign_direction=d) for d in range(16)]
    blocks += [B("wall_sign", facing_direction=d) for d in range(6)] + [B("bed", direction=d) for d in range(4)]
    blocks += [B("stone_button", facing_direction=d, button_pressed_bit=p) for d in range(6) for p in (0, 1)]
    blocks += [B(name) for name, s in sorted(SPECS.items()) if not s["states"]][:200]
    rng = np.random.default_rng(n)
    expect = {}
    for i in range(4096):
        x, y, z = i // 256, i % 16, (i // 16) % 16
        b = blocks[rng.integers(n)] if n > 1 else blocks[0]
        w.set(x, 16 + y, z, b)
        expect[(x, y, z)] = b
    recs = dict(w.chunk_records(0, 0))
    sy, idx, palette = decode_subchunk(recs[struct.pack("<ii", 0, 0) + b"/\x01"])
    assert sy == 1
    names = [(p["name"][10:], p["states"]) for p in palette]
    for (x, y, z), b in list(expect.items())[::7]:
        name, states = names[idx[x, z, y]]
        assert name == b.name and states == b.nbt()["states"]


def test_block_states_are_checked():
    assert B("oak_log").nbt()["states"] == {"pillar_axis": "y"}
    with pytest.raises(KeyError):
        B("oak_door")  # Bedrock calls it wooden_door
    with pytest.raises(ValueError):
        B("standing_sign", ground_sign_direction=16)
    with pytest.raises(KeyError):
        B("stone", color="red")


def test_gym_maze_is_winnable_and_has_no_loops():
    grid = gym_puzzle.layout()
    assert all(len(r) == gym_puzzle.COLS for r in grid) and len(grid) == gym_puzzle.ROWS
    for r, row in enumerate(grid):
        for c, ch in enumerate(row):
            if ch in gym_puzzle.DIRS:
                gym_puzzle.slide(grid, c, r)  # raises on a loop
    prev = gym_puzzle.solve(grid)
    assert gym_puzzle.goal(grid) in prev
    # it is a puzzle: walking straight north from the entrance only gets you pushed back
    assert gym_puzzle.slide(grid, 15, 25)[1] >= 26


@pytest.fixture(scope="module")
def world():
    return places.build()


def test_whole_area_has_ground(world):
    x0, z0, x1, z1 = places.BOUNDS
    assert set(world.chunks) == {(cx, cz) for cx in range(x0 >> 4, (x1 >> 4) + 1)
                                 for cz in range(z0 >> 4, (z1 >> 4) + 1)}
    for (cx, cz), c in world.chunks.items():
        assert (c[:, 0, :] == world._index[B("bedrock")]).all(), (cx, cz)


def test_spawn_and_doors_are_walkable(world):
    x, y, z = places.SPAWN
    assert world.get(x, y - 1, z) != AIR and world.get(x, y, z) == AIR and world.get(x, y + 1, z) == AIR
    lower = [i for i, b in enumerate(world.palette) if b.name == "wooden_door" and not dict(b.states)["upper_block_bit"]]
    doors = 0
    for (cx, cz), c in world.chunks.items():
        for lx, yi, lz in zip(*np.nonzero(np.isin(c, lower))):
            x, y, z = cx * 16 + lx, yi + MIN_Y, cz * 16 + lz
            assert world.get(x, y + 1, z).name == "wooden_door"
            doors += 1
            for dz in (-1, 1):  # doors sit in east-west walls: clear inside and outside
                assert world.get(x, y, z + dz) in (AIR,) or "carpet" in world.get(x, y, z + dz).name, (x, y, z)
    assert doors >= 5


def test_signs_and_buttons(world):
    signs = world.meta["signs"]
    assert len(signs) > 20
    for s in signs:
        x, y, z = s["p"]
        assert world.get(x, y, z).name in ("standing_sign", "wall_sign")
        be = world.block_entities[(x, y, z)]
        assert be["id"] == "Sign" and be["FrontText"]["Text"] == s["t"] and be["IsWaxed"]
        assert all(len(line) <= 15 for line in s["t"].split("\n")) and s["t"].count("\n") <= 3, s["t"]
        if world.get(x, y, z).name == "standing_sign":
            assert world.get(x, y - 1, z) != AIR, s
    actions = {b["a"] for b in world.meta["buttons"]}
    assert actions == {"heal", "give", "starter", "badge"}
    for b in world.meta["buttons"]:
        x, y, z = b["p"]
        assert world.get(x, y, z).name == "stone_button"
        assert world.get(x, y - 1, z) != AIR and "slab" not in world.get(x, y - 1, z).name


def test_gym_tiles_match_the_grid(world):
    (sp,) = world.meta["spinners"]
    ox, oz = sp["o"]
    for r, row in enumerate(sp["g"]):
        for c, ch in enumerate(row):
            b = world.get(ox + c, sp["y"], oz + r)
            if ch in gym_puzzle.DIRS:
                assert b.name == "magenta_glazed_terracotta"
                assert world.get(ox + c, sp["y"] + 1, oz + r) == AIR
            elif ch == "#":
                assert world.get(ox + c, sp["y"] + 2, oz + r) != AIR


def test_mcworld_contents(world, tmp_path):
    from kanto.__main__ import FLAT, PACK

    level = level_dat("Kanto", places.SPAWN, FLAT)
    out = world.write(tmp_path / "Kanto", level, pack_dir=PACK)
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert {"level.dat", "levelname.txt", "db/CURRENT", "db/MANIFEST-000002", "db/000003.log",
                "world_behavior_packs.json", "behavior_packs/KantoScripts/manifest.json",
                "behavior_packs/KantoScripts/scripts/main.js",
                "behavior_packs/KantoScripts/scripts/kanto_data.js"} <= names
        manifest = json.loads(z.read("behavior_packs/KantoScripts/manifest.json"))
        packs = json.loads(z.read("world_behavior_packs.json"))
        assert packs == [{"pack_id": manifest["header"]["uuid"], "version": manifest["header"]["version"]}]
        raw = z.read("level.dat")
    version, length = struct.unpack_from("<ii", raw)
    assert version == 10 and length == len(raw) - 8
    dat, _ = nbt.loads(raw, 8)
    assert dat["GameType"] == 2 and dat["Difficulty"] == 0 and [dat["SpawnX"], dat["SpawnY"], dat["SpawnZ"]] == list(places.SPAWN)
    keys = {k for k, _ in leveldb.read_log(tmp_path / "Kanto" / "db")}
    assert struct.pack("<ii", 0, 0) + b"," in keys
    assert any(k.endswith(b"1") and len(k) == 9 for k in keys)  # block entities written


def test_amulet_reads_the_world(world, tmp_path):
    """Independent check with Amulet (built on Mojang's LevelDB) when it is installed."""
    amulet = pytest.importorskip("amulet")
    from kanto.__main__ import FLAT

    world.write(tmp_path / "Kanto", level_dat("Kanto", places.SPAWN, FLAT))
    lvl = amulet.load_level(str(tmp_path / "Kanto"))
    try:
        for p in [places.SPAWN, (20, -60, 27), *[tuple(s["p"]) for s in world.meta["signs"][:5]]]:
            got, _ = lvl.get_version_block(*p, "minecraft:overworld", ("bedrock", (26, 40, 0)))
            assert got.base_name == world.get(*p).name, p
    finally:
        lvl.close()
