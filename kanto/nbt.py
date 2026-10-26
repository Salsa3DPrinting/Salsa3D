"""Little-endian NBT writer (the Bedrock flavor), just enough for chunks, block entities and level.dat.

Python values map to tags: dict -> compound, str -> string, bool -> byte, int -> int, float -> float.
Wrap a value in Byte/Short/Long/Double or List to pick another tag.
"""

from __future__ import annotations

import struct

END, BYTE, SHORT, INT, LONG, FLOAT, DOUBLE, BYTE_ARRAY, STRING, LIST, COMPOUND = range(11)


class Byte(int):
    pass


class Short(int):
    pass


class Long(int):
    pass


class Double(float):
    pass


class List(list):
    """List tag; `tag` is the element type (needed for empty lists)."""

    def __init__(self, items=(), tag: int | None = None):
        super().__init__(items)
        self.tag = tag if tag is not None else (tag_of(self[0]) if self else END)


def tag_of(v) -> int:
    if isinstance(v, (bool, Byte)):
        return BYTE
    if isinstance(v, Short):
        return SHORT
    if isinstance(v, Long):
        return LONG
    if isinstance(v, int):
        return INT
    if isinstance(v, Double):
        return DOUBLE
    if isinstance(v, float):
        return FLOAT
    if isinstance(v, str):
        return STRING
    if isinstance(v, List):
        return LIST
    if isinstance(v, list):
        return LIST
    if isinstance(v, dict):
        return COMPOUND
    raise TypeError(f"no NBT tag for {type(v).__name__}")


def _str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<H", len(b)) + b


def _payload(v, tag: int) -> bytes:
    if tag == BYTE:
        return struct.pack("<b", int(v))
    if tag == SHORT:
        return struct.pack("<h", v)
    if tag == INT:
        return struct.pack("<i", v)
    if tag == LONG:
        return struct.pack("<q", v)
    if tag == FLOAT:
        return struct.pack("<f", v)
    if tag == DOUBLE:
        return struct.pack("<d", v)
    if tag == STRING:
        return _str(v)
    if tag == LIST:
        lst = v if isinstance(v, List) else List(v)
        if any(tag_of(x) != lst.tag for x in lst):
            raise TypeError("NBT list items must share one type")
        return struct.pack("<bi", lst.tag, len(lst)) + b"".join(_payload(x, lst.tag) for x in lst)
    if tag == COMPOUND:
        out = [struct.pack("<b", tag_of(x)) + _str(k) + _payload(x, tag_of(x)) for k, x in v.items()]
        return b"".join(out) + b"\x00"
    raise TypeError(f"unsupported tag {tag}")


def dumps(root: dict, name: str = "") -> bytes:
    """Serialize a root compound."""
    return struct.pack("<b", COMPOUND) + _str(name) + _payload(root, COMPOUND)


def loads(data: bytes, offset: int = 0) -> tuple[dict, int]:
    """Parse one root compound; returns (value, end offset). Used by tests to read back what we wrote."""
    def rd(fmt):
        nonlocal offset
        v = struct.unpack_from(fmt, data, offset)
        offset += struct.calcsize(fmt)
        return v[0]

    def rstr():
        nonlocal offset
        n = rd("<H")
        s = data[offset:offset + n].decode("utf-8")
        offset += n
        return s

    def payload(tag):
        if tag == BYTE:
            return Byte(rd("<b"))
        if tag == SHORT:
            return Short(rd("<h"))
        if tag == INT:
            return rd("<i")
        if tag == LONG:
            return Long(rd("<q"))
        if tag == FLOAT:
            return rd("<f")
        if tag == DOUBLE:
            return Double(rd("<d"))
        if tag == STRING:
            return rstr()
        if tag == LIST:
            t, n = rd("<b"), rd("<i")
            return List([payload(t) for _ in range(n)], tag=t)
        if tag == COMPOUND:
            out = {}
            while (t := rd("<b")) != END:
                k = rstr()
                out[k] = payload(t)
            return out
        raise ValueError(f"unsupported tag {tag} at {offset}")

    if rd("<b") != COMPOUND:
        raise ValueError("root is not a compound")
    rstr()
    return payload(COMPOUND), offset
