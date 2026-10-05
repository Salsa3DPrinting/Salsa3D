"""In-memory stand-in for the Meshy API, shaped after the documented responses."""

from __future__ import annotations

import json
import re

import trimesh


def box_glb(extents_m=(0.02, 0.05, 0.03)) -> bytes:
    """A GLB box in meters, Y-up (glTF convention): Y is the height."""
    return trimesh.Scene(trimesh.creation.box(extents=extents_m)).export(file_type="glb")


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
        if endpoint == "/v1/print/analyze":
            verdict = "healthy" if t["payload"].get("model_url") else self.verdict
            body.update(consumed_credits=0, printability={"status": verdict, "error_count": int(verdict == "error")})
        else:
            credits = 10 if endpoint == "/v1/print/repair" else 20
            body.update(consumed_credits=credits, thumbnail_url=f"https://assets.example/{task_id}/preview.png",
                        model_urls={"glb": f"https://assets.example/{task_id}/model.glb", "stl": ""})
        return FakeResponse(body=body)

    # requests.Session.get (downloads)
    def get(self, url, stream=False, timeout=None):
        self.calls.append(("DOWNLOAD", url, None))
        return FakeResponse(content=self.glb if url.endswith(".glb") else b"\x89PNG")
