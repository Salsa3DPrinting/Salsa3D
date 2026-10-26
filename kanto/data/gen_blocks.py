"""One-off (run with PyMCTranslate installed): extract Bedrock block specs (PyMCTranslate 26.40) checked against Mojang's 26.50 block list."""
import json
import sys

import PyMCTranslate

with open(sys.argv[1]) as f:
    mojang = json.load(f)
moj = {b["name"].split(":", 1)[1]: sorted(p["name"] for p in b.get("properties", [])) for b in mojang["data_items"]}
tm = PyMCTranslate.new_translation_manager()
v = tm.get_version("bedrock", (26, 40, 0))
out, skipped = {}, []
for name in sorted(v.block.base_names("minecraft", force_blockstate=True)):
    if name not in moj:
        skipped.append(name)
        continue
    spec = v.block.get_specification("minecraft", name, force_blockstate=True)
    props = {}
    for p, vals in spec.get("properties", {}).items():
        t = "b" if vals[0].endswith("b") else "s" if vals[0].startswith('"') else "i"
        conv = (lambda s: int(s[:-1])) if t == "b" else (lambda s: json.loads(s)) if t == "s" else int
        props[p] = {"type": t, "values": [conv(x) for x in vals], "default": conv(spec["defaults"][p])}
    entry = {"states": props}
    if sorted(props) != moj[name]:
        # states changed after 26.40 (e.g. stairs corner, fence connections): written in the 26.40 form and
        # upgraded by the game on load, since the palette carries the 26.40 block version.
        entry["newer_states"] = sorted(set(moj[name]) - set(props))
    if spec.get("nbt_identifier"):
        entry["block_entity"] = spec["nbt_identifier"][1]
    out[name] = entry
with open(sys.argv[2], "w") as f:
    json.dump({"block_version": v.data_version,
               "source": "PyMCTranslate bedrock 26.40, names/states checked against Mojang bedrock-samples 1.26.50.4",
               "blocks": out}, f, separators=(",", ":"), sort_keys=True)
print(len(out), "blocks;", len(skipped), "skipped:", skipped[:40], file=sys.stderr)
