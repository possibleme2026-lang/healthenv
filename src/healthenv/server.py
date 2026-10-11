"""Dependency-free HTTP server for the HealthEnv browser environment."""

from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .runtime import ActionError, TaskRuntime
from .schema import TaskSpec


class HealthEnvHandler(BaseHTTPRequestHandler):
    runtime: TaskRuntime

    def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _asset(self, name: str) -> None:
        safe_name = name.replace("..", "").lstrip("/") or "index.html"
        asset = files("healthenv.assets").joinpath(safe_name)
        if not asset.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = asset.read_bytes()
        content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/healthz":
            self._json({"ok": True, "task_id": self.runtime.task.task_id})
        elif path == "/api/task":
            self._json(self.runtime.public_task())
        elif path == "/api/state":
            self._json(self.runtime.snapshot())
        elif path == "/api/verify":
            self._json(self.runtime.verification())
        elif path in {"/", "/index.html"}:
            self._asset("index.html")
        else:
            self._asset(path)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/action":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 100_000:
                raise ActionError("invalid request body size")
            action = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(action, dict):
                raise ActionError("action body must be an object")
            state = self.runtime.apply(action)
            payload: dict[str, Any] = {"ok": True, "state": state}
            if action.get("type") == "submit":
                payload["verification"] = self.runtime.verification()
            self._json(payload)
        except (ActionError, UnicodeDecodeError, json.JSONDecodeError) as error:
            self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"healthenv {self.address_string()} {format % args}")


def load_task(path: str | Path) -> TaskSpec:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return TaskSpec.from_dict(raw)


def serve(task_path: str | Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    task = load_task(task_path)
    runtime = TaskRuntime(task)
    handler = type("BoundHealthEnvHandler", (HealthEnvHandler,), {"runtime": runtime})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"HealthEnv task {task.task_id} running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
