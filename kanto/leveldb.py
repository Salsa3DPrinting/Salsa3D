"""Write a LevelDB database as a single write-ahead log, the way Mojang ships its own world templates.

The game replays the log into tables the first time it opens the world, so no compression or table
format is needed here. Layout: CURRENT -> MANIFEST-000002 (comparator, log number 3) -> 000003.log.
"""

from __future__ import annotations

import struct
from pathlib import Path

BLOCK = 32768
FULL, FIRST, MIDDLE, LAST = 1, 2, 3, 4
BATCH_BYTES = 1 << 20

_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ 0x82F63B78 if _c & 1 else _c >> 1
    _TABLE.append(_c)


def crc32c(data: bytes, crc: int = 0) -> int:
    crc ^= 0xFFFFFFFF
    t = _TABLE
    for b in data:
        crc = t[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


try:  # optional C implementation, same result
    import google_crc32c as _gcrc

    def crc32c(data: bytes, crc: int = 0) -> int:
        return _gcrc.extend(crc, data)
except ImportError:
    pass


def _masked_crc(data: bytes) -> int:
    c = crc32c(data)
    return (((c >> 15) | (c << 17)) + 0xA282EAD8) & 0xFFFFFFFF


def _varint(n: int) -> bytes:
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


class _LogWriter:
    def __init__(self, f):
        self.f = f
        self.offset = 0  # position inside the current 32 KiB block

    def add_record(self, data: bytes) -> None:
        begin = True
        while True:
            left = BLOCK - self.offset
            if left < 7:  # no room for a header: pad the block with zeros
                self.f.write(b"\x00" * left)
                self.offset = 0
                left = BLOCK
            n = min(len(data), left - 7)
            end = n == len(data)
            kind = FULL if begin and end else FIRST if begin else LAST if end else MIDDLE
            frag = data[:n]
            self.f.write(struct.pack("<IHB", _masked_crc(bytes([kind]) + frag), n, kind) + frag)
            self.offset += 7 + n
            data = data[n:]
            begin = False
            if end:
                return


def write_db(path: Path, items) -> int:
    """Write (key, value) pairs to a fresh database directory; returns the number of records."""
    path.mkdir(parents=True, exist_ok=True)
    seq, count = 1, 0
    with open(path / "000003.log", "wb") as f:
        log = _LogWriter(f)
        batch, nbatch, size = [], 0, 0

        def flush():
            nonlocal seq, batch, nbatch, size
            if nbatch:
                log.add_record(struct.pack("<QI", seq, nbatch) + b"".join(batch))
                seq += nbatch
            batch, nbatch, size = [], 0, 0

        for key, value in items:
            rec = b"\x01" + _varint(len(key)) + key + _varint(len(value)) + value
            batch.append(rec)
            nbatch += 1
            count += 1
            size += len(rec)
            if size >= BATCH_BYTES:
                flush()
        flush()

    with open(path / "MANIFEST-000002", "wb") as f:
        log = _LogWriter(f)
        cmp = b"leveldb.BytewiseComparator"
        log.add_record(b"\x01" + _varint(len(cmp)) + cmp)
        # log number 3, prev log 0, next file 4, last sequence 0 (the log replay sets the real one)
        log.add_record(b"\x02\x03\x09\x00\x03\x04\x04\x00")
    (path / "CURRENT").write_bytes(b"MANIFEST-000002\n")
    return count


def read_log(path: Path):
    """Yield (key, value) records from a log, value None for deletions (later records win). For tests."""
    data = (path / "000003.log").read_bytes()
    off, buf = 0, b""
    while off + 7 <= len(data):
        left = BLOCK - off % BLOCK
        if left < 7:
            off += left
            continue
        crc, n, kind = struct.unpack_from("<IHB", data, off)
        if kind == 0 and n == 0:
            off += left
            continue
        frag = data[off + 7: off + 7 + n]
        if _masked_crc(bytes([kind]) + frag) != crc:
            raise ValueError(f"bad crc at {off}")
        off += 7 + n
        buf += frag
        if kind in (FULL, LAST):
            yield from _parse_batch(buf)
            buf = b""


def _parse_batch(b: bytes):
    _, count = struct.unpack_from("<QI", b, 0)
    off = 12

    def varint():
        nonlocal off
        shift = val = 0
        while True:
            c = b[off]
            off += 1
            val |= (c & 0x7F) << shift
            if c < 0x80:
                return val
            shift += 7

    for _ in range(count):
        kind = b[off]
        off += 1
        k = varint()
        key = b[off:off + k]
        off += k
        if kind == 0:  # deletion
            yield key, None
            continue
        v = varint()
        yield key, b[off:off + v]
        off += v
