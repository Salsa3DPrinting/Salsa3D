"""In-memory Bedrock world: set blocks, then write a .mcworld (LevelDB chunks + level.dat + behavior pack).

Coordinates are game coordinates: x east, z south, y up (overworld -64..319). Chunk records follow the
format the game writes itself: chunk version 40, sub-chunk format 9 (one storage layer, XZY order),
Data3D heightmap + single plains biome, finalized state 2.
"""

from __future__ import annotations

import json
import shutil
import struct
import zipfile
from pathlib import Path

import numpy as np

from kanto import leveldb, nbt
from kanto.blocks import AIR, Block

MIN_Y, MAX_Y = -64, 319
HEIGHT = MAX_Y - MIN_Y + 1
CHUNK_VERSION = 40
PLAINS = 1
BITS = (1, 2, 3, 4, 5, 6, 8, 16)


class World:
    def __init__(self):
        self.chunks: dict[tuple[int, int], np.ndarray] = {}  # (cx, cz) -> uint16[16 x, 384 y, 16 z]
        self.palette: list[Block] = [AIR]
        self._index = {AIR: 0}
        self.block_entities: dict[tuple[int, int, int], dict] = {}
        self.meta: dict[str, list] = {}  # data handed to the behavior pack script
        self.ground: dict[tuple[int, int], int] = {}  # (x, z) -> y of the top ground block, set by terrain

    # ---- blocks ----
    def _id(self, b: Block) -> int:
        i = self._index.get(b)
        if i is None:
            i = self._index[b] = len(self.palette)
            self.palette.append(b)
        return i

    def _chunk(self, cx: int, cz: int) -> np.ndarray:
        c = self.chunks.get((cx, cz))
        if c is None:
            c = self.chunks[(cx, cz)] = np.zeros((16, HEIGHT, 16), np.uint16)
        return c

    def fill(self, x0, y0, z0, x1, y1, z1, b: Block) -> None:
        """Fill the inclusive box between two corners."""
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        z0, z1 = sorted((z0, z1))
        if y0 < MIN_Y or y1 > MAX_Y:
            raise ValueError(f"y {y0}..{y1} outside {MIN_Y}..{MAX_Y}")
        i = self._id(b)
        for cx in range(x0 >> 4, (x1 >> 4) + 1):
            for cz in range(z0 >> 4, (z1 >> 4) + 1):
                ax0, ax1 = max(x0, cx * 16) - cx * 16, min(x1, cx * 16 + 15) - cx * 16
                az0, az1 = max(z0, cz * 16) - cz * 16, min(z1, cz * 16 + 15) - cz * 16
                self._chunk(cx, cz)[ax0:ax1 + 1, y0 - MIN_Y:y1 - MIN_Y + 1, az0:az1 + 1] = i

    def set(self, x, y, z, b: Block) -> None:
        self.fill(x, y, z, x, y, z, b)

    def get(self, x, y, z) -> Block:
        c = self.chunks.get((x >> 4, z >> 4))
        return AIR if c is None else self.palette[c[x & 15, y - MIN_Y, z & 15]]

    def column_top(self, x, z) -> int:
        """Highest non-air y in a column (MIN_Y - 1 if empty)."""
        c = self.chunks.get((x >> 4, z >> 4))
        if c is None:
            return MIN_Y - 1
        nz = np.nonzero(c[x & 15, :, z & 15])[0]
        return int(nz[-1]) + MIN_Y if len(nz) else MIN_Y - 1

    def block_entity(self, x, y, z, ident: str, **data) -> None:
        self.block_entities[(x, y, z)] = {"id": ident, "isMovable": nbt.Byte(1), **data, "x": x, "y": y, "z": z}

    def add_meta(self, kind: str, item) -> None:
        self.meta.setdefault(kind, []).append(item)

    # ---- encoding ----
    def _subchunk(self, sub: np.ndarray, sy: int) -> bytes:
        ids, inv = np.unique(sub.transpose(0, 2, 1).ravel(), return_inverse=True)  # XZY order
        bits = next(b for b in BITS if (1 << b) >= len(ids))
        per = 32 // bits
        nwords = -(-4096 // per)
        vals = np.zeros(nwords * per, np.uint32)
        vals[:4096] = inv
        words = np.zeros(nwords, np.uint32)
        for k in range(per):
            words |= vals[k::per] << np.uint32(k * bits)
        palette = b"".join(nbt.dumps(self.palette[i].nbt()) for i in ids)
        return (bytes([9, 1, sy & 0xFF, bits << 1]) + words.astype("<u4").tobytes()
                + struct.pack("<i", len(ids)) + palette)

    def chunk_records(self, cx: int, cz: int):
        c = self.chunks[(cx, cz)]
        pre = struct.pack("<ii", cx, cz)
        yield pre + b",", bytes([CHUNK_VERSION])
        nonair = c != 0
        top = np.where(nonair.any(axis=1), HEIGHT - np.argmax(nonair[:, ::-1, :], axis=1), 0)  # [x, z]
        data3d = top.astype("<i2").ravel().tobytes() + b"\x01" + struct.pack("<i", PLAINS) + b"\xff" * 23
        yield pre + b"+", data3d
        for sy in range(MIN_Y // 16, (MAX_Y + 1) // 16):
            sub = c[:, (sy * 16 - MIN_Y):(sy * 16 - MIN_Y) + 16, :]
            if sub.any():
                yield pre + b"/" + bytes([sy & 0xFF]), self._subchunk(sub, sy)
        bes = [be for (x, _, z), be in sorted(self.block_entities.items()) if (x >> 4, z >> 4) == (cx, cz)]
        if bes:
            yield pre + b"1", b"".join(nbt.dumps(be) for be in bes)
        yield pre + b"6", struct.pack("<i", 2)

    def records(self):
        for be in self.block_entities:
            if (be[0] >> 4, be[2] >> 4) not in self.chunks:
                raise ValueError(f"block entity at {be} is outside written chunks")
        for cx, cz in sorted(self.chunks):
            yield from self.chunk_records(cx, cz)

    # ---- output ----
    def write(self, folder: Path, level_dat: dict, pack_dir: Path | None = None, icon: Path | None = None) -> Path:
        """Write the world folder and a zipped .mcworld next to it; returns the .mcworld path."""
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        leveldb.write_db(folder / "db", self.records())
        body = nbt.dumps(level_dat)
        (folder / "level.dat").write_bytes(struct.pack("<ii", level_dat["StorageVersion"], len(body)) + body)
        (folder / "levelname.txt").write_text(level_dat["LevelName"])
        if icon:
            shutil.copy(icon, folder / "world_icon.jpeg")
        if pack_dir:
            manifest = json.loads((pack_dir / "manifest.json").read_text())
            shutil.copytree(pack_dir, folder / "behavior_packs" / pack_dir.name)
            (folder / "behavior_packs" / pack_dir.name / "scripts" / "kanto_data.js").write_text(
                "// Generated by python -m kanto: positions of signs, buttons, regions and gym tiles.\n"
                "export const DATA = " + json.dumps(self.meta, separators=(",", ":")) + ";\n")
            h = manifest["header"]
            (folder / "world_behavior_packs.json").write_text(
                json.dumps([{"pack_id": h["uuid"], "version": h["version"]}], indent=2))
        out = folder.with_suffix(".mcworld")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(folder.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(folder).as_posix())
        return out


def flat_layers_json(layers: list[tuple[str, int]]) -> str:
    """FlatWorldLayers string for chunks outside the build (same encoding the game writes)."""
    return json.dumps({"biome_id": PLAINS, "block_layers": [{"block_name": "minecraft:" + n, "count": c}
                                                            for n, c in layers],
                       "encoding_version": 6, "structure_options": None, "world_version": "version.post_1_18"},
                      separators=(",", ":"))

