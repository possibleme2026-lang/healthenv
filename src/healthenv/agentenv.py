"""Agent-facing tool server for HealthEnv.

A benchmark episode needs one thing from every harness: a way to observe the
environment and take actions in it. Rather than teach each harness a bespoke
protocol, this module exposes a tiny, self-describing HTTP tool surface:

    GET  /manifest    the tool list, with argument schemas
    GET  /tool        execute one tool call from query parameters
    POST /tool        execute one tool call from a JSON body

The surface is deliberately narrow. ``submit`` returns no verifier signal, so a
harness cannot hill-climb against the gold answer, and ``/api/verify`` is not
reachable from here at all.

Every call is appended to a trajectory, which is what makes cross-harness
comparison meaningful: identical tasks, identical tools, identical scoring, so
any difference we measure comes from the harness rather than the interface.

Why two transports
------------------
The harnesses do not share a shell. On Windows ``pi`` drives Git Bash while
``codex`` and ``dsh`` drive PowerShell 5.1, and the two disagree about how a
quoted JSON argument reaches ``curl``. Measured directly, this prompt line

    curl -X POST <url>/tool -d '{"tool":"get_task","args":{}}'

works verbatim in bash but reaches the server through PowerShell as
``{tool:get_task,args:{}}`` -- PowerShell strips the inner double quotes, so the
body is no longer JSON and the call fails for reasons that have nothing to do
with the agent's reasoning. A GET query contains no inner quotes at all and both
shells transmit it byte-identically, so the documented call uses GET and POST is
kept as an equally supported alias. Without this, a harness comparison would be
measuring shell quoting rather than the harness.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .runtime import ActionError, TaskRuntime
from .schema import TaskSpec
from .verifier import verify_state

# Each entry maps an agent-facing tool to the environment action it performs.
TOOL_MANIFEST: tuple[dict[str, Any], ...] = (
    {
        "name": "get_task",
        "description": "Return the task instruction and the participant header.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_records",
        "description": "Return every source record. Records are read-only observations.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_state",
        "description": "Return the working state: selected evidence, note, priority, submitted flag.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "select_record",
        "description": "Add or remove one record from the selected evidence set.",
        "parameters": {
            "type": "object",
            "properties": {
                "record_id": {"type": "string", "description": "The id of the record to toggle."},
                "selected": {"type": "boolean", "description": "True to select, false to deselect."},
            },
            "required": ["record_id", "selected"],
        },
    },
    {
        "name": "set_note",
        "description": "Replace the care note with a grounded conclusion.",
        "parameters": {
            "type": "object",
            "properties": {"note": {"type": "string"}},
            "required": ["note"],
        },
    },
    {
        "name": "set_status",
        "description": (
            "Set the workflow priority. Low-risk findings are routine, findings that need a "
            "clinician's attention are review, and findings that need immediate action are urgent."
        ),
        "parameters": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["routine", "review", "urgent"]}},
            "required": ["status"],
        },
    },
    {
        "name": "submit",
        "description": (
            "Submit the completed task for offline scoring. This ends the episode and returns no "
            "feedback about correctness."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
)

# Each entry maps an agent-facing tool to the environment action it performs.
def _select_action(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "select_record",
        "record_id": args.get("record_id"),
        "selected": args.get("selected", True),
    }


def _set_note_action(args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "set_note", "note": args.get("note", "")}


def _set_status_action(args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "set_status", "status": args.get("status")}


def _submit_action(_args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "submit"}


_ACTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "select_record": _select_action,
    "set_note": _set_note_action,
    "set_status": _set_status_action,
    "submit": _submit_action,
}


class Episode:
    """One agent run against one environment, with a recorded trajectory."""

    def __init__(self, task: TaskSpec, *, max_steps: int = 60) -> None:
        self.task = task
        self.runtime = TaskRuntime(task)
        self.max_steps = max_steps
        self.trajectory: list[dict[str, Any]] = []
        self.submitted = False

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if self.submitted:
            return {"ok": False, "error": "episode already submitted"}
        if len(self.trajectory) >= self.max_steps:
            return {"ok": False, "error": f"step budget of {self.max_steps} exhausted"}
        try:
            if tool == "get_task":
                result: dict[str, Any] = self.runtime.agent_task()
            elif tool == "list_records":
                result = {"records": self.task.records}
            elif tool == "read_state":
                result = self.runtime.snapshot()
            elif tool in _ACTIONS:
                state = self.runtime.apply(_ACTIONS[tool](args))
                if tool == "submit":
                    self.submitted = True
                    result = {"ok": True, "submitted": True}
                else:
                    result = {"ok": True, "state": state}
            else:
                return {"ok": False, "error": f"unknown tool {tool!r}"}
        except (ActionError, KeyError, TypeError) as error:
            self.trajectory.append({"tool": tool, "args": args, "error": str(error)})
            return {"ok": False, "error": str(error)}
        self.trajectory.append({"tool": tool, "args": args, "ok": True})
        return result

    def score(self) -> dict[str, Any]:
        report = verify_state(self.task, self.runtime.snapshot())
        return {
            "task_id": self.task.task_id,
            "strict_success": report.strict_success,
            "score": report.score,
            "checks": [check.name for check in report.checks if not check.passed],
            "steps": len(self.trajectory),
            "tool_calls": [entry["tool"] for entry in self.trajectory],
        }


def _parse_typed(raw: str) -> Any:
    """Decode a query value into the type the tool's schema declares.

    Everything arrives from a query string as text, so ``selected=false`` would
    otherwise be the truthy string ``"false"``. Only scalars are coerced; the
    tool surface has no structured arguments, and a hand-written coercion is
    safer than an eval-shaped shortcut.
    """
    if raw == "true":
        return True
    if raw == "false":
        return False
    return raw


def _args_from_query(params: dict[str, list[str]]) -> tuple[str, dict[str, Any]]:
    """Split a query mapping into the tool name and its arguments."""
    tool = params.get("tool", [""])[0]
    args = {
        key: _parse_typed(values[0])
        for key, values in params.items()
        if key != "tool" and values
    }
    return tool, args


class ToolHandler(BaseHTTPRequestHandler):
    episode: Episode

    def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/healthz":
            self._json({"ok": True, "task_id": self.episode.task.task_id})
        elif path == "/manifest":
            self._json(
                {
                    "task_id": self.episode.task.task_id,
                    "tools": list(TOOL_MANIFEST),
                    "max_steps": self.episode.max_steps,
                }
            )
        elif path == "/tool":
            # Shell-agnostic transport: a query string survives bash and
            # PowerShell unchanged, where a quoted JSON body does not.
            tool, args = _args_from_query(parse_qs(urlparse(self.path).query))
            self._json(self.episode.call(tool, args))
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/tool":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 100_000:
                raise ActionError("invalid request body size")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ActionError("tool call must be an object")
            tool = str(payload.get("tool", ""))
            args = payload.get("args", {})
            if not isinstance(args, dict):
                raise ActionError("args must be an object")
            self._json(self.episode.call(tool, args))
        except (ActionError, UnicodeDecodeError, json.JSONDecodeError) as error:
            self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        # keep the harness transcript clean; trajectories are recorded separately
        pass


def serve_episode(
    task: TaskSpec, *, host: str = "127.0.0.1", port: int = 0, max_steps: int = 60
) -> tuple[ThreadingHTTPServer, Episode]:
    """Start a tool server for one episode on an OS-assigned port."""
    episode = Episode(task, max_steps=max_steps)
    handler = type("BoundToolHandler", (ToolHandler,), {"episode": episode})
    server = ThreadingHTTPServer((host, port), handler)
    return server, episode
