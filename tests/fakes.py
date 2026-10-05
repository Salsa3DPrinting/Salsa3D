"""In-memory stand-in for the Meshy API, shaped after the documented responses."""

from __future__ import annotations

import json
import re

import trimesh


def box_glb(extents_m=(0.02, 0.05, 0.03)) -> bytes:
    """A GLB box in meters, Y-up (glTF convention): Y is the height."""
    return trimesh.Scene(trimesh.creation.box(extents=extents_m)).export(file_type="glb")


def two_part_glb() -> bytes:
    """An assembled 2-part model in meters, Y-up: a 0.03 m body with a 0.02 m head on top."""
    body = trimesh.creation.box(extents=[0.02, 0.03, 0.02])
    head = trimesh.creation.box(extents=[0.015, 0.02, 0.015])
    head.apply_translation([0, 0.025, 0])
    scene = trimesh.Scene()
    scene.add_geometry(body, node_name="body", geom_name="body")
    scene.add_geometry(head, node_name="head", geom_name="head")
    return scene.export(file_type="glb")


def two_object_3mf(size_mm=(20, 20, 30)) -> bytes:
    a = trimesh.creation.box(extents=size_mm)
    b = trimesh.creation.box(extents=[5, 5, 5])
    b.apply_translation([30, 0, 0])
    scene = trimesh.Scene()
    scene.add_geometry(a, node_name="a", geom_name="a")
    scene.add_geometry(b, node_name="b", geom_name="b")
    return scene.export(file_type="3mf")


class FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None, content=b""):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.content = content
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# model_urls a Creative Lab build returns, per preset (from the docs' example responses).
PRESET_OUTPUTS = {
    "keychain": {"glb": "model.glb"},
    "fridge-magnet": {"glb": "model.glb"},
    "figure": {"glb": "model.glb", "obj": "model.obj", "mtl": "model.mtl"},
    "vinyl-figure": {"glb": "model.glb"},
    "brick-figure": {"glb": "model.glb"},
    "keycap": {"glb": "model.glb", "obj_zip": "model-obj.zip"},
    "lamp": {"lamp_stl": "lamp.stl", "base_stl": "base.stl"},
    "fidget-pixel": {"3mf": "model.3mf"},
    "fidget-collapsible": {"glb": "model.glb", "stl": "model.stl"},
}
PRESET_CREDITS = {"prototype": 6, "build": 30}


class FakeMeshy:
    """Acts as both the API session and the asset download session."""

    def __init__(self, verdict="healthy", polls_before_done=1, glb=None, fail_endpoint=None):
        self.headers: dict[str, str] = {}
        self.verdict = verdict
        self.polls_before_done = polls_before_done
        self.glb = glb or box_glb()
        self.fail_endpoint = fail_endpoint
        self.tasks: dict[str, dict] = {}
        self.calls: list[tuple[str, str, dict | None]] = []
        self.queued: list[FakeResponse] = []

    def posts(self, suffix: str) -> list[dict]:
        return [c[2] for c in self.calls if c[0] == "POST" and c[1].endswith(suffix)]

    # requests.Session.request
    def request(self, method, url, json=None, timeout=None):
        self.calls.append((method, url, json))
        if self.queued:
            return self.queued.pop(0)
        path = url.split("/openapi", 1)[1]
        if method == "GET" and path == "/v1/balance":
            return FakeResponse(body={"balance": 1000})
        if method == "POST":
            task_id = f"task-{len(self.tasks) + 1}"
            self.tasks[task_id] = {"endpoint": path, "payload": json, "polls": 0}
            return FakeResponse(202, {"result": task_id})
        m = re.match(r"^(.*)/(task-\d+)$", path)
        if method == "GET" and m:
            return self._task(m.group(1), m.group(2))
        return FakeResponse(404, {"message": "Not found"})

    def _task(self, endpoint, task_id):
        t = self.tasks[task_id]
        t["polls"] += 1
        if t["polls"] <= self.polls_before_done:
            return FakeResponse(body={"id": task_id, "status": "IN_PROGRESS", "progress": 50},
                                headers={"Retry-After": "3"})
        if endpoint == self.fail_endpoint:
            return FakeResponse(body={"id": task_id, "status": "FAILED", "progress": 0,
                                      "task_error": {"message": "boom"}})
        body = {"id": task_id, "status": "SUCCEEDED", "progress": 100, "expires_at": 1, "task_error": None}
        assets = f"https://assets.example/{task_id}"
        lab = re.match(r"^/creative-lab/([a-z-]+)/v1(/prototype|/build)?$", endpoint)
        if endpoint == "/v1/print/analyze":
            verdict = "healthy" if t["payload"].get("model_url") else self.verdict
            body.update(consumed_credits=0, printability={"status": verdict, "error_count": int(verdict == "error")})
        elif endpoint == "/v1/print/multi-color":
            body.update(consumed_credits=10, model_urls={"3mf": f"{assets}/model.3mf?Expires=1"})
        elif endpoint == "/v1/print/split":
            body.update(consumed_credits=10, part_count=2, model_urls={"glb": f"{assets}/split.glb?Expires=1"})
        elif lab and lab.group(2) == "/prototype":
            body.update(consumed_credits=PRESET_CREDITS["prototype"],
                        image_urls=[f"{assets}/concept.png?Expires=1"])
            if lab.group(1) == "keycap":
                body["candidate_ids"] = ["cand-1", "cand-2"]
        elif lab:
            body.update(consumed_credits=PRESET_CREDITS["build"],
                        model_urls={k: f"{assets}/{v}?Expires=1" for k, v in PRESET_OUTPUTS[lab.group(1)].items()})
        else:
            credits = 10 if endpoint == "/v1/print/repair" or t["payload"].get("mode") == "refine" else 20
            body.update(consumed_credits=credits, thumbnail_url=f"{assets}/preview.png",
                        model_urls={"glb": f"{assets}/model.glb", "stl": ""})
        return FakeResponse(body=body)

    # requests.Session.get (downloads)
    def get(self, url, stream=False, timeout=None):
        self.calls.append(("DOWNLOAD", url, None))
        name = url.split("?")[0].rsplit("/", 1)[-1]
        if name == "split.glb":
            content = two_part_glb()
        elif name.endswith(".glb"):
            content = self.glb
        elif name.endswith(".stl"):
            content = trimesh.creation.box(extents=[100, 100, 120]).export(file_type="stl")
        elif name.endswith(".3mf"):
            content = two_object_3mf()
        else:
            content = b"\x89PNG"
        return FakeResponse(content=content)
