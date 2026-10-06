"""Fan library and the adapter app's local API (no browser, no network)."""

import json
import math
import threading
import urllib.error
import urllib.request

import pytest

from cad import fanlib
from cad.adapter_app import server

GOOD = {"name": "Test 80 fan", "frame": 80, "corner_r": 5, "depth": 25, "hole_d": 4.5, "bore_d": 70,
        "hub_d": 30, "hub_proud": 0, "bolt_circle_d": 101.1}


def test_validate_and_spacing_conversion():
    fan, errors = fanlib.validate({**GOOD, "bolt_circle_d": "", "hole_spacing": 71.5})
    assert errors == []
    assert fan.id == "test-80-fan"
    assert fan.bolt_circle_d == pytest.approx(71.5 * math.sqrt(2))


@pytest.mark.parametrize("change,msg", [
    ({"bore_d": 90}, "smaller than the frame"),
    ({"bolt_circle_d": 130}, "outside the frame"),
    ({"bore_d": 78, "bolt_circle_d": 88}, "too close to the air opening"),
    ({"hub_d": 75}, "Hub plate must be smaller"),
    ({"frame": "abc"}, "must be a number"),
    ({"name": ""}, "Name is required"),
])
def test_validate_rejects(change, msg):
    fan, errors = fanlib.validate({**GOOD, **change})
    assert fan is None and any(msg in e for e in errors), errors


def test_library_save_load_delete(tmp_path):
    lib = tmp_path / "shared" / "fans.json"
    fan, _ = fanlib.validate(GOOD)
    fanlib.save(fan, lib)
    assert "test-80-fan" in fanlib.load(lib) and "bfs-i06" in fanlib.load(lib)
    with pytest.raises(ValueError, match="already exists"):
        fanlib.save(fan, lib)
    fanlib.save(fan, lib, overwrite=True)
    builtin, _ = fanlib.validate({**GOOD, "name": "BFS-i06"})
    with pytest.raises(ValueError, match="built-in"):
        fanlib.save(builtin, lib)
    fanlib.delete("test-80-fan", lib)
    assert "test-80-fan" not in fanlib.load(lib)


@pytest.fixture
def app(tmp_path):
    srv = server.make_server(server.State(tmp_path), 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path
    srv.shutdown()


def call(url, body=None, headers=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_api_flow(app):
    url, root = app
    status, body = call(url + "/api/catalog")
    cat = json.loads(body)
    assert status == 200 and cat["fans"][0]["id"] == "bfs-i06"
    assert {"pvc-spigot", "pvc-socket", "npt-male", "npt-female", "triclamp"} <= set(cat["fittings"])

    status, body = call(url + "/api/generate", {"a": "bfs-i06", "b": "pvc-5-sch40-spigot"})
    assert status == 400 and b"no PVC data" in body

    status, body = call(url + "/api/fans", {"fan": {**GOOD, "bore_d": 90}})
    assert status == 400 and json.loads(body)["errors"]
    status, _ = call(url + "/api/fans", {"fan": GOOD})
    assert status == 200 and (root / "fans.json").exists()

    status, body = call(url + "/api/generate", {"a": "test-80-fan", "b": "triclamp-1.5",
                                                "options": {"taper_deg": 20}})
    rep = json.loads(body)
    assert status == 200 and rep["watertight"] and rep["options"]["taper_deg"] == 20
    status, stl = call(f"{url}/api/jobs/{rep['job']}/{rep['stem']}.stl")
    assert status == 200 and len(stl) > 1000
    assert call(f"{url}/api/jobs/{rep['job']}/..%2F..%2Fsettings.json")[0] == 404
    assert call(f"{url}/api/jobs/..%2F/fans.json")[0] == 404
    # Requests from another site's page are refused.
    assert call(url + "/api/fans/delete", {"id": "test-80-fan"}, {"Origin": "http://evil.example"})[0] == 403
