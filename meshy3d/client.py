"""Thin client for the Meshy REST API (https://docs.meshy.ai).

Every generation endpoint is asynchronous: POST returns {"result": task_id},
then GET /<endpoint>/<id> is polled until status is terminal.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://api.meshy.ai/openapi"

# Endpoint paths relative to BASE_URL.
TEXT_TO_3D = "/v2/text-to-3d"
IMAGE_TO_3D = "/v1/image-to-3d"
PRINT_ANALYZE = "/v1/print/analyze"
PRINT_REPAIR = "/v1/print/repair"
BALANCE = "/v1/balance"

TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELED"}


class MeshyError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, task: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.task = task


class MeshyClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_429_retries: int = 5,
        download_session: requests.Session | None = None,
    ):
        api_key = api_key or os.environ.get("MESHY_API_KEY")
        if not api_key:
            raise MeshyError("MESHY_API_KEY is not set")
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"
        self.sleep = sleep
        self.max_429_retries = max_429_retries
        # Asset URLs are pre-signed; this session never carries the API key.
        self.download_session = download_session or requests.Session()

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        for attempt in range(self.max_429_retries + 1):
            resp = self.session.request(method, self.base_url + path, timeout=60, **kwargs)
            if resp.status_code == 429 and attempt < self.max_429_retries:
                self.sleep(_retry_after(resp, default=2 ** attempt))
                continue
            if resp.status_code >= 400:
                try:
                    message = resp.json().get("message", resp.text)
                except ValueError:
                    message = resp.text
                raise MeshyError(f"{method} {path} -> HTTP {resp.status_code}: {message}", resp.status_code)
            return resp
        raise AssertionError("unreachable")

    def balance(self) -> int:
        return self._request("GET", BALANCE).json()["balance"]

    def create_task(self, endpoint: str, payload: dict[str, Any]) -> str:
        return self._request("POST", endpoint, json=payload).json()["result"]

    def get_task(self, endpoint: str, task_id: str) -> tuple[dict, requests.Response]:
        resp = self._request("GET", f"{endpoint}/{task_id}")
        return resp.json(), resp

    def wait_for_task(
        self,
        endpoint: str,
        task_id: str,
        timeout_s: float = 1800,
        on_progress: Callable[[dict], None] | None = None,
    ) -> dict:
        """Poll until the task is terminal, honoring Retry-After. Raises on FAILED/CANCELED."""
        deadline = time.monotonic() + timeout_s
        while True:
            task, resp = self.get_task(endpoint, task_id)
            if on_progress:
                on_progress(task)
            status = task.get("status")
            if status == "SUCCEEDED":
                return task
            if status in TERMINAL_STATUSES:
                err = (task.get("task_error") or {}).get("message") or "no error message"
                raise MeshyError(f"Task {task_id} {status}: {err}", task=task)
            if time.monotonic() > deadline:
                raise MeshyError(f"Timed out waiting for task {task_id} (last status {status})", task=task)
            self.sleep(_retry_after(resp, default=5))

    def run_task(self, endpoint: str, payload: dict[str, Any], **wait_kwargs) -> dict:
        task_id = self.create_task(endpoint, payload)
        return self.wait_for_task(endpoint, task_id, **wait_kwargs)

    def download(self, url: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self.download_session.get(url, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                f.writelines(resp.iter_content(chunk_size=1 << 20))
        return dest


def _retry_after(resp: requests.Response, default: float) -> float:
    try:
        return max(float(resp.headers.get("Retry-After", default)), 1.0)
    except ValueError:
        return default
