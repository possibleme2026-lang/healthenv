"""Drive a stratified sample of compiled environments through a real browser.

The scale pipeline proves every environment at the state-verifier level. This
script proves the part that level cannot: that the environment is actually
*reachable through its GUI*. It boots one HTTP server per sampled task, drives
each one in a real headless browser (click the evidence checkboxes, type the
note, set the priority, submit), and asserts a 100% strict success.

Sampling is stratified over (surface, required status, reasoning skill), so one
sample per cell covers every combination the generator can produce.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from healthenv.runtime import TaskRuntime
from healthenv.sampling import stratified_sample
from healthenv.schema import TaskSpec
from healthenv.server import HealthEnvHandler, load_task

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS_DIR = ROOT / "generated" / "scale"
DEFAULT_ARTIFACT = ROOT / "artifacts" / "browser_batch.json"
NODE_CANDIDATES = (
    os.environ.get("HEALTHENV_NODE", ""),
    r"C:\Users\less\.workbuddy\binaries\node\versions\22.22.2-6\node.exe",
    "node",
)
CHROME_CANDIDATES = (
    os.environ.get("HEALTHENV_CHROME", ""),
    r"C:\Users\less\AppData\Local\ms-playwright\chromium_headless_shell-1208"
    r"\chrome-headless-shell-win64\chrome-headless-shell.exe",
    "chrome-headless-shell",
    "google-chrome",
)


def _find_executable(candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return str(path)
        from shutil import which

        resolved = which(candidate)
        if resolved:
            return resolved
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class _Server:
    """An HTTP server for one task, bound to an OS-assigned port."""

    def __init__(self, task: TaskSpec) -> None:
        runtime = TaskRuntime(task)
        handler = type("BoundHandler", (HealthEnvHandler,), {"runtime": runtime})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.log = lambda *args: None  # keep bulk runs readable
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{int(self.httpd.server_address[1])}"

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


# This used to be an independent copy of the sampler in
# scripts/harness_eval.py, and the two diverged: the copy here sorted the cells
# alphabetically, so for any --limit below the cell count every pick landed in
# the first cell and the sample collapsed onto clinical-ledger -- measured, the
# artifact recorded 6/6 ledger tasks for --limit 6. Both drivers now alias the
# shared implementation, which interleaves surfaces on every pick.
_stratified_sample = stratified_sample


def _manifest_item(task: TaskSpec, server: _Server) -> dict[str, Any]:
    terms = [str(term) for term in task.verifier.get("note_must_include", [])]
    return {
        "task_id": task.task_id,
        "url": server.url,
        "surface": str(task.source.get("surface", "timeline")),
        "category": str(task.source.get("category", "unknown")),
        "status": str(task.verifier.get("required_status", "review")),
        "evidence": [str(item) for item in task.verifier.get("required_evidence_ids", [])],
        "note": " ".join(terms),
        "expected_selected": len(task.verifier.get("required_evidence_ids", [])),
        "record_count": len(task.records),
    }


def _cdp_ready(port: int, attempts: int = 60) -> bool:
    import urllib.request

    for _ in range(attempts):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as response:
                return response.status == 200
        except OSError:
            time.sleep(0.25)
    return False


def _run_chunk(
    tasks: list[TaskSpec],
    *,
    node: str,
    cdp_port: int,
    script: Path,
    last: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Serve one chunk of tasks and drive them through the browser.

    Servers are started per chunk and torn down before the next one: booting
    all 1200 at once would hold 1200 bound sockets and 1200 runtimes in memory,
    which is not a thing this machine (or the claim) needs.
    """
    servers: list[_Server] = []
    try:
        items: list[dict[str, Any]] = []
        for task in tasks:
            server = _Server(task)
            server.start()
            servers.append(server)
            items.append(_manifest_item(task, server))

        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            manifest_path.write_text(json.dumps({"items": items}, indent=2), encoding="utf-8")
            completed = subprocess.run(
                [node, str(script), str(manifest_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env={**os.environ, "CDP_PORT": str(cdp_port), "KEEP_BROWSER": "" if last else "1"},
                timeout=1800,
            )
            stdout = completed.stdout.strip()
            if completed.returncode != 0 or not stdout:
                print(completed.stdout[-4000:])
                print(completed.stderr[-4000:])
                raise RuntimeError("browser driver exited without a report")
            payload = json.loads(stdout)
        return items, list(payload.get("results", []))
    finally:
        for server in servers:
            server.stop()


def _chunks(tasks: list[TaskSpec], size: int) -> list[list[TaskSpec]]:
    return [tasks[index : index + size] for index in range(0, len(tasks), size)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS_DIR)
    parser.add_argument("--limit", type=int, default=63)
    parser.add_argument("--chunk-size", type=int, default=50)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--cdp-port", type=int, default=9333)
    args = parser.parse_args()

    node = _find_executable(NODE_CANDIDATES)
    chrome = _find_executable(CHROME_CANDIDATES)
    if node is None or chrome is None:
        report = {
            "browser_available": False,
            "reason": f"missing executable (node={node!r}, chrome={chrome!r})",
            "sampled": 0,
            "passed": 0,
            "results": [],
        }
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0

    task_paths = sorted(args.tasks_dir.glob("*.json"))
    if not task_paths:
        print(f"FAIL: no compiled tasks in {args.tasks_dir}")
        return 1
    tasks = [load_task(path) for path in task_paths]
    sample = _stratified_sample(tasks, args.limit)

    browser = subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={args.cdp_port}",
            f"--user-data-dir={Path(tempfile.gettempdir()) / f'healthenv-batch-{args.cdp_port}'}",
            "--no-sandbox",
            "--disable-gpu",
            "--no-proxy-server",
            "--disable-dev-shm-usage",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    script = ROOT / "tools" / "browser_batch.mjs"
    items: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    chunks = _chunks(sample, args.chunk_size)
    try:
        if not _cdp_ready(args.cdp_port):
            print("FAIL: browser debug endpoint never became ready")
            return 1
        for index, chunk in enumerate(chunks, start=1):
            chunk_items, chunk_results = _run_chunk(
                chunk,
                node=node,
                cdp_port=args.cdp_port,
                script=script,
                last=index == len(chunks),
            )
            items.extend(chunk_items)
            results.extend(chunk_results)
            passed = sum(1 for result in chunk_results if result.get("passed"))
            print(
                f"chunk {index}: {passed}/{len(chunk)} passed "
                f"({len(results)}/{len(sample)} total)",
                flush=True,
            )
    finally:
        browser.terminate()
        try:
            browser.wait(timeout=10)
        except subprocess.TimeoutExpired:
            browser.kill()

    passed = sum(1 for result in results if result.get("passed"))
    payload: dict[str, Any] = {
        "browser_available": True,
        "sampled": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "surfaces": sorted({result["surface"] for result in results}),
        "statuses": sorted({result["status"] for result in results}),
        "categories": sorted({result["category"] for result in results}),
        "results": results,
        "sampled_cells": len({(i["surface"], i["status"], i["category"]) for i in items}),
        "manifest": items,
    }
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({k: v for k, v in payload.items() if k not in {"results", "manifest"}}, indent=2))
    if payload["passed"] != payload["sampled"]:
        for result in results:
            if not result.get("passed"):
                print(f"FAIL: {result.get('task_id')} :: {result.get('failure')}")
                print(f"      rendered: {json.dumps(result.get('rendered'), sort_keys=True)}")
        return 1
    print(f"OK: {payload['passed']}/{payload['sampled']} environments driven to strict success in-browser")
    return 0


if __name__ == "__main__":
    sys.exit(main())
