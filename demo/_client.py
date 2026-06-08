"""Minimal stdlib HTTP client for the KubeRAG gateway.

No third-party dependencies - uses urllib so the demo runs with a bare Python 3
interpreter. Override the gateway URL with the KUBERAG_URL environment variable.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("KUBERAG_URL", "http://localhost:8000/api/v1")


def request(method: str, path: str, data=None, token: str | None = None,
            form: bool = False, timeout: int = 60) -> dict:
    url = BASE + path
    headers: dict[str, str] = {}
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def login(username: str = "admin", password: str = "admin") -> str:
    resp = request("POST", "/auth/token",
                   {"username": username, "password": password}, form=True)
    return resp["access_token"]


def poll(token: str, job_id: str, timeout: int = 240, interval: float = 1.0) -> dict:
    """Poll a job until it reaches a terminal state or the timeout elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = request("GET", f"/query/{job_id}", token=token)
        if state.get("status") in ("completed", "failed"):
            return state
        time.sleep(interval)
    return {"status": "timeout", "job_id": job_id}
