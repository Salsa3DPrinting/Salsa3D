"""Bedrock block states, checked against the vendored spec in data/bedrock_blocks.json.

`B("oak_log", pillar_axis="x")` returns a Block with every state filled in (defaults for the rest), or
raises if the name, a state, or a value would not exist in game. The palette version written to disk is
the spec's block version; the game upgrades it on load (data/gen_blocks.py documents the source).
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import NamedTuple

from kanto import nbt

_SPEC = json.loads((Path(__file__).parent / "data" / "bedrock_blocks.json").read_text())
BLOCK_VERSION: int = _SPEC["block_version"]
SPECS: dict = _SPEC["blocks"]


class Block(NamedTuple):
    name: str
    states: tuple  # sorted (state, value) pairs

    def nbt(self) -> dict:
        states = {}
        for k, v in self.states:
            t = SPECS[self.name]["states"][k]["type"]
            states[k] = nbt.Byte(v) if t == "b" else v
        return {"name": "minecraft:" + self.name, "states": states, "version": BLOCK_VERSION}

    def with_(self, **states) -> Block:
        return B(self.name, **{**dict(self.states), **states})


@cache
def _make(name: str, given: tuple) -> Block:
    spec = SPECS.get(name)
    if spec is None:
        raise KeyError(f"unknown Bedrock block {name!r}")
    states = {k: s["default"] for k, s in spec["states"].items()}
    for k, v in given:
        s = spec["states"].get(k)
        if s is None:
            raise KeyError(f"{name} has no state {k!r} (has {sorted(spec['states'])})")
        if isinstance(v, bool):
            v = int(v)
        if v not in s["values"]:
            raise ValueError(f"{name}.{k}={v!r} not in {s['values']}")
        states[k] = v
    return Block(name, tuple(sorted(states.items())))


def B(name: str, **states) -> Block:
    return _make(name, tuple(sorted(states.items())))


AIR = B("air")
