"""Local web server for the adapter generator. Runs on 127.0.0.1 only and opens the browser.

Run: python -m cad.adapter_app [--port 8765] [--no-browser] [--selftest]
The Windows build (packaging/) wraps this same entry point into SalsaAdapter.exe.

Data lives in a per-user folder (%APPDATA%\\SalsaAdapter on Windows, ~/.salsa-adapter elsewhere):
settings.json, fans.json (the user fan library, unless settings point it at a shared drive) and output/,
one folder per generated adapter.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import webbrowser
from dataclasses import asdict, fields, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from cad import adapter, fanlib

STATIC = Path(__file__).parent / "static"
MAX_BODY = 64 * 1024
JOB_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9-]{1,80}$")
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".png": "image/png", ".json": "application/json",
                 ".stl": "model/stl", ".3mf": "model/3mf", ".txt": "text/plain; charset=utf-8",
                 ".svg": "image/svg+xml"}


def data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "SalsaAdapter"
    return Path.home() / ".salsa-adapter"


class State:
    def __init__(self, root: Path):
        self.root = root
        self.settings_file = root / "settings.json"
        self.lock = threading.Lock()   # one adapter build at a time
        self.settings = {"fan_library": str(root / "fans.json"), "output_dir": str(root / "output")}
        if self.settings_file.exists():
            try:
                self.settings.update(json.loads(self.settings_file.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    @property
    def library(self) -> Path:
        return Path(self.settings["fan_library"]).expanduser()

    @property
    def output(self) -> Path:
        return Path(self.settings["output_dir"]).expanduser()

    def save_settings(self, new: dict) -> None:
        for key in ("fan_library", "output_dir"):
            value = str(new.get(key, "")).strip()
            if not value:
                raise ValueError(f"{key.replace('_', ' ')} can't be empty")
            self.settings[key] = value
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings_file.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")

    def fans(self) -> dict[str, fanlib.Fan]:
        return fanlib.load(self.library)


def fan_json(fan: fanlib.Fan) -> dict:
    d = asdict(fan)
    d["hole_spacing"] = round(fan.bolt_circle_d / 2 ** 0.5, 2)
    return d


def options_from(raw: dict) -> adapter.Options:
    known = {f.name for f in fields(adapter.Options)}
    vals = {}
    for k, v in (raw or {}).items():
        if k in known and v not in (None, ""):
            try:
                vals[k] = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k.replace('_', ' ')} must be a number") from None
    opt = replace(adapter.DEFAULT, **vals)
    opt.check()
    return opt


def generate(state: State, body: dict) -> dict:
    a, b = str(body.get("a", "")).strip(), str(body.get("b", "")).strip()
    if not a or not b:
        raise ValueError("Pick both ends of the adapter")
    opt = options_from(body.get("options"))
    fans = state.fans()
    # Parse both ends first so a typo comes back right away, before any geometry work.
    adapter.parse_fitting(a, fans, opt)
    adapter.parse_fitting(b, fans, opt)
    job = f"{time.strftime('%Y%m%d-%H%M%S')}-{adapter.slug(a)[:38]}-to-{adapter.slug(b)[:38]}"
    out = state.output / job
    with state.lock:
        report = adapter.generate(a, b, out, opt, fans)
    report["job"] = job
    report["folder"] = str(out)
    return report


class Handler(BaseHTTPRequestHandler):
    state: State
    server_version = "SalsaAdapter"

    def log_message(self, fmt, *args):  # keep the console quiet except for errors
        pass

    # --- helpers ---
    def send_json(self, obj, status=200):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path: Path, download: bool = False):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("Request too large")
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def guard(self, fn):
        try:
            fn()
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001 - report it, don't kill the server
            traceback.print_exc()
            self.send_json({"error": f"Unexpected error: {e}"}, 500)

    def local_only(self) -> bool:
        # Refuse requests that a web page on another site could forge (DNS rebinding / cross-site POSTs).
        host = (self.headers.get("Host") or "").split(":")[0]
        origin = self.headers.get("Origin")
        if host not in ("127.0.0.1", "localhost") or (origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost")):
            self.send_json({"error": "forbidden"}, 403)
            return False
        return True

    # --- routes ---
    def do_GET(self):
        if not self.local_only():
            return
        path = unquote(urlparse(self.path).path)
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return None
        if path in ("/", "/index.html"):
            return self.send_file(STATIC / "index.html")
        if path.startswith("/static/"):
            f = (STATIC / path[len("/static/"):]).resolve()
            if STATIC.resolve() in f.parents and f.is_file():
                return self.send_file(f)
            return self.send_json({"error": "not found"}, 404)
        if path == "/api/catalog":
            return self.guard(lambda: self.send_json(self.catalog()))
        m = re.match(r"^/api/jobs/([^/]+)/([^/]+)$", path)
        if m:
            job, name = m.groups()
            folder = self.state.output / job
            f = folder / name
            if JOB_RE.match(job) and f.parent == folder and f.is_file() and "/" not in name and "\\" not in name:
                return self.send_file(f, download="download" in (urlparse(self.path).query or ""))
            return self.send_json({"error": "not found"}, 404)
        self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.local_only():
            return
        path = urlparse(self.path).path
        if path == "/api/generate":
            return self.guard(lambda: self.send_json(generate(self.state, self.body())))
        if path == "/api/fans":
            return self.guard(self.add_fan)
        if path == "/api/fans/delete":
            return self.guard(self.delete_fan)
        if path == "/api/settings":
            return self.guard(self.save_settings)
        if path == "/api/open-folder":
            return self.guard(self.open_folder)
        if path == "/api/quit":
            self.send_json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        self.send_json({"error": "not found"}, 404)

    def catalog(self) -> dict:
        try:
            fans = self.state.fans()
            fan_error = None
        except (OSError, ValueError) as e:
            fans, fan_error = fanlib.load(None), f"Could not read the fan library: {e}"
        return {
            "fans": [fan_json(f) for f in sorted(fans.values(), key=lambda f: f.name.lower())],
            "fan_error": fan_error,
            "fan_fields": {k: {"label": v[0], "help": v[1], "min": v[2], "max": v[3]}
                           for k, v in fanlib.NUMERIC_FIELDS.items()},
            "fittings": adapter.catalog(),
            "defaults": asdict(adapter.DEFAULT),
            "settings": self.state.settings,
            "version": adapter.GENERATOR_VERSION,
        }

    def add_fan(self):
        body = self.body()
        fan, errors = fanlib.validate(body.get("fan") or {})
        if errors:
            return self.send_json({"errors": errors}, 400)
        fanlib.save(fan, self.state.library, overwrite=bool(body.get("overwrite")))
        self.send_json({"ok": True, "fan": fan_json(fan)})

    def delete_fan(self):
        fanlib.delete(str(self.body().get("id", "")), self.state.library)
        self.send_json({"ok": True})

    def save_settings(self):
        self.state.save_settings(self.body())
        self.send_json({"ok": True, "settings": self.state.settings})

    def open_folder(self):
        job = str(self.body().get("job", ""))
        folder = self.state.output / job
        if not JOB_RE.match(job) or not folder.is_dir():
            raise ValueError("No such output folder")
        if hasattr(os, "startfile"):
            os.startfile(folder)  # Windows Explorer
        self.send_json({"ok": True, "folder": str(folder)})


def make_server(state: State, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"state": state})
    for p in (port, 0):  # fall back to any free port if the preferred one is taken
        try:
            return ThreadingHTTPServer(("127.0.0.1", p), handler)
        except OSError:
            continue
    raise OSError("Could not open a local port")


def selftest() -> int:
    """Build one threaded adapter and hit the API once; used by the Windows build to check the bundle."""
    with tempfile.TemporaryDirectory() as tmp:
        state = State(Path(tmp))
        report = generate(state, {"a": "bfs-i06", "b": "npt-2-male"})
        ok = report["watertight"] and report["bodies"] == 1 and len(report["files"]) >= 4
        srv = make_server(state, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        cat = json.loads(urllib.request.urlopen(url + "/api/catalog", timeout=30).read())
        page = urllib.request.urlopen(url + "/", timeout=30).read()
        ok = ok and any(f["id"] == "bfs-i06" for f in cat["fans"]) and b"Adapter" in page
        srv.shutdown()
    print("selftest", "OK" if ok else "FAILED", json.dumps({k: report[k] for k in ("title", "files", "warnings")}))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Salsa duct adapter generator (local web app)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--data-dir", type=Path, default=None, help="settings/library/output folder")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    state = State(args.data_dir or data_dir())
    srv = make_server(state, args.port)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"Salsa adapter generator {adapter.GENERATOR_VERSION} running at {url}")
    print(f"Fan library: {state.library}")
    print(f"Output folder: {state.output}")
    print("Leave this window open while you use the app; close it (or press Ctrl+C) to stop.")
    sys.stdout.flush()
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0
