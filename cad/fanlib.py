"""Fan library: built-in fans (cad/data/fans.json) plus a user library file that the adapter app's form writes.

A fan is a square frame with 4 mounting holes at 45 deg on a bolt circle and a round air opening. The user
library can live on a shared drive so colleagues see each other's fans; writes are atomic (temp file + rename)
and re-read the file first, so two people adding fans at different times don't overwrite each other.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

BUILTIN_FILE = Path(__file__).parent / "data" / "fans.json"


@dataclass(frozen=True)
class Fan:
    id: str
    name: str
    frame: float           # square frame side, mm
    corner_r: float
    depth: float
    bolt_circle_d: float   # circle through the 4 hole centers (holes at 45, 135, 225, 315 deg)
    hole_d: float
    bore_d: float          # air opening on the frame face
    hub_d: float           # motor hub plate diameter (proud of one face); 0 if none
    hub_proud: float
    verified: bool = False
    added_by: str = ""
    notes: str = ""
    added_on: str = ""
    builtin: bool = False

    @property
    def hole_angles(self) -> tuple[float, ...]:
        return (45.0, 135.0, 225.0, 315.0)


# Form fields: key -> (label, help, min, max). Lengths in mm.
NUMERIC_FIELDS = {
    "frame": ("Frame size", "Outside width of the square frame", 20, 400),
    "corner_r": ("Corner radius", "Radius of the frame's rounded corners (0 for sharp)", 0, 200),
    "depth": ("Fan depth", "Overall thickness of the fan, face to face (for reference)", 5, 400),
    "bolt_circle_d": ("Bolt circle diameter", "Circle through the 4 hole centers", 10, 600),
    "hole_d": ("Hole diameter", "Mounting hole diameter", 1, 40),
    "bore_d": ("Air opening diameter", "Round opening on the frame face the air flows through", 10, 400),
    "hub_d": ("Hub plate diameter", "Motor hub plate that sticks out of one face (0 if flush)", 0, 400),
    "hub_proud": ("Hub plate height", "How far the hub plate sticks out past the frame face (0 if flush)", 0, 50),
}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def validate(data: dict, adapter_wall: float = 3.5) -> tuple[Fan | None, list[str]]:
    """Check a form submission. Accepts the hole pattern as 'bolt_circle_d' or as 'hole_spacing' (square,
    center to center), which is converted. Returns (fan, errors)."""
    errors = []
    data = dict(data)
    name = str(data.get("name", "")).strip()
    if not name:
        errors.append("Name is required.")
    spacing = data.pop("hole_spacing", None)
    if spacing not in (None, "") and data.get("bolt_circle_d") in (None, ""):
        try:
            data["bolt_circle_d"] = float(spacing) * math.sqrt(2)
        except ValueError:
            errors.append("Hole spacing must be a number.")
    vals = {}
    for key, (label, _, lo, hi) in NUMERIC_FIELDS.items():
        raw = data.get(key)
        if raw in (None, ""):
            if key in ("hub_d", "hub_proud", "corner_r"):
                vals[key] = 0.0
                continue
            errors.append(f"{label} is required.")
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            errors.append(f"{label} must be a number.")
            continue
        if not lo <= v <= hi:
            errors.append(f"{label} must be between {lo} and {hi} mm.")
        vals[key] = v
    if errors:
        return None, errors

    half = vals["frame"] / 2
    hole_xy = vals["bolt_circle_d"] / 2 / math.sqrt(2)  # hole center x = y at 45 deg
    if vals["corner_r"] > half:
        errors.append("Corner radius can't be more than half the frame size.")
    if vals["bore_d"] >= vals["frame"]:
        errors.append("Air opening must be smaller than the frame.")
    if hole_xy + vals["hole_d"] / 2 > half - 1.0:
        errors.append(f"Holes fall outside the frame: hole centers at ±{hole_xy:.1f} mm, frame edge at ±{half:.1f} mm.")
    if vals["bolt_circle_d"] / 2 - vals["hole_d"] / 2 < vals["bore_d"] / 2 + adapter_wall:
        errors.append("Holes are too close to the air opening to leave room for the adapter wall.")
    if vals["hub_d"] and vals["hub_d"] >= vals["bore_d"]:
        errors.append("Hub plate must be smaller than the air opening (or the adapter would sit on it).")
    if errors:
        return None, errors
    fan = Fan(id=slugify(str(data.get("id") or name)), name=name, **vals,
              verified=bool(data.get("verified", False)), added_by=str(data.get("added_by", "")).strip(),
              notes=str(data.get("notes", "")).strip(), added_on=str(data.get("added_on") or datetime.now().astimezone().date()))
    if not fan.id:
        return None, ["Name must contain letters or numbers."]
    return fan, []


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc.get("fans", [])


def _from_dict(d: dict, builtin: bool) -> Fan:
    known = {f.name for f in fields(Fan)}
    return Fan(**{k: v for k, v in d.items() if k in known and k != "builtin"}, builtin=builtin)


def load(library: Path | None = None) -> dict[str, Fan]:
    fans = {d["id"]: _from_dict(d, True) for d in _read(BUILTIN_FILE)}
    if library is not None:
        for d in _read(library):
            if d.get("id") not in fans:  # built-ins win; the app refuses to save over them anyway
                fans[d["id"]] = _from_dict(d, False)
    return fans


def save(fan: Fan, library: Path, overwrite: bool = False) -> None:
    """Add (or with overwrite, replace) a fan in the user library."""
    if fan.id in load(None):
        raise ValueError(f"'{fan.id}' is a built-in fan; pick another name.")
    entries = _read(library)
    exists = any(d.get("id") == fan.id for d in entries)
    if exists and not overwrite:
        raise ValueError(f"A fan named '{fan.id}' already exists in the library.")
    d = {k: v for k, v in asdict(fan).items() if k != "builtin"}
    entries = [d if e.get("id") == fan.id else e for e in entries] if exists else entries + [d]
    _write(library, entries)


def delete(fan_id: str, library: Path) -> None:
    entries = _read(library)
    if not any(d.get("id") == fan_id for d in entries):
        raise ValueError(f"No fan '{fan_id}' in the library (built-in fans can't be deleted).")
    _write(library, [d for d in entries if d.get("id") != fan_id])


def _write(library: Path, entries: list[dict]) -> None:
    library.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=library.parent, prefix=".fans-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"fans": sorted(entries, key=lambda d: d["name"].lower())}, f, indent=2)
    os.replace(tmp, library)
