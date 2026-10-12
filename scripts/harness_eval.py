"""Cross-harness evaluation: same tasks, same tools, three different agents.

Every harness reads the same prompt and calls the same HTTP tools, so the only
variable left is the harness itself. Episodes are scored offline by the
deterministic verifier after the agent submits, which means a harness never sees
a correctness signal mid-episode and cannot steer toward the gold answer.

Usage:
    python scripts/harness_eval.py --harnesses pi,codex,deepseek --limit 12
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from healthenv.agentenv import serve_episode
from healthenv.harness import (
    DEFAULT_BASE_URL,
    build_prompt,
    describe_command,
    harness_env,
    harness_specs,
    resolve_command,
)
from healthenv.sampling import stratified_sample
from healthenv.schema import TaskSpec
from healthenv.server import load_task

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS_DIR = ROOT / "generated" / "scale"
DEFAULT_ARTIFACT = ROOT / "artifacts" / "harness_eval.json"


def _api_key() -> str | None:
    """Resolve the shared credential without ever logging it.

    Precedence: an explicit benchmark variable, then the codex store the task
    already authenticated against, then the pi store.
    """
    for name in ("HEALTHENV_API_KEY", "TIERFLOW_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value
    for candidate in (Path.home() / ".codex" / ".env",):
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENAI_API_KEY="):
                    return line.split("=", 1)[1].strip()
    pi_models = Path.home() / ".pi" / "agent" / "models.json"
    if pi_models.is_file():
        payload = json.loads(pi_models.read_text(encoding="utf-8"))
        provider = payload.get("providers", {}).get("tierflow", {})
        if isinstance(provider, dict) and provider.get("apiKey"):
            return str(provider["apiKey"])
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


# Shared with scripts/browser_batch.py so the two artifacts cannot report
# surface breakdowns produced by different samplers. The docstring on
# healthenv.sampling records why surface interleaving is load-bearing.
_stratified_sample = stratified_sample


class ToolServer:
    """Runs one episode's tool server on its own port."""

    def __init__(self, task: TaskSpec, *, max_steps: int) -> None:
        self.server, self.episode = serve_episode(task, port=_free_port(), max_steps=max_steps)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{int(self.server.server_address[1])}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _as_text(value: Any) -> str:
    """Normalize a subprocess stream that may arrive as bytes or text."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _run_harness(
    spec: Any,
    *,
    prompt: str,
    cwd: Path,
    api_key: str,
    timeout: int,
    episode: Any = None,
    early_exit: bool = True,
) -> dict[str, Any]:
    """Run one harness, stopping it shortly after the episode is submitted.

    Output goes to files rather than pipes. Pipes can deadlock here: the harness
    spawns children (``npx`` and a shell it drives) that inherit the write end,
    so reading until EOF can block long after the main process is done. Files
    have no such coupling, and a sibling thread can watch for completion.

    Completion is read from the episode, not from the transcript. Asking the
    agent to print a marker does not work: codex echoes the prompt to stderr, so
    the marker text appears in the echo and a transcript match kills the run
    before it starts. The tool server already knows when ``submit`` lands, so the
    watcher polls that and gives the process a short grace period to exit on its
    own before the group is killed.
    """
    from healthenv.harness import (
        PROMPT_FILENAME,
        PROMPT_TRANSPORT_STDIN,
        prompt_file,
    )

    for name, content in spec.setup_files.items():
        target = cwd / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    # every harness gets the prompt on disk; how it is reached differs per CLI
    (cwd / PROMPT_FILENAME).write_text(prompt_file(prompt), encoding="utf-8")

    requested = spec.build_command(prompt, str(cwd))
    env = harness_env(spec, api_key, DEFAULT_BASE_URL, str(cwd))
    argv = resolve_command(requested, env)
    out_path = cwd / "stdout.log"
    err_path = cwd / "stderr.log"
    stdin_path: Path | None = None
    if spec.prompt_transport == PROMPT_TRANSPORT_STDIN:
        stdin_path = cwd / "stdin.txt"
        stdin_path.write_text(prompt_file(prompt), encoding="utf-8")

    started = time.perf_counter()
    terminate = threading.Event()
    timed_out = False
    returncode = -1
    with out_path.open("w", encoding="utf-8", errors="replace") as out_file, err_path.open(
        "w", encoding="utf-8", errors="replace"
    ) as err_file:
        stdin_source: Any = subprocess.DEVNULL
        stdin_handle = stdin_path.open("rb") if stdin_path else None
        if stdin_handle:
            stdin_source = stdin_handle
        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdin=stdin_source,
                stdout=out_file,
                stderr=err_file,
                **(
                    {"start_new_session": True}
                    if os.name == "posix"
                    else {"creationflags": 0x00000200}
                ),
            )
        finally:
            if stdin_handle:
                stdin_handle.close()

        def _watcher() -> None:
            from healthenv.harness import GRACE_SECONDS

            deadline = time.monotonic() + timeout
            done_at: float | None = None
            while process.poll() is None:
                if early_exit and episode is not None and getattr(episode, "submitted", False):
                    # the agent submitted; give it a moment to exit by itself
                    if done_at is None:
                        done_at = time.monotonic()
                    elif time.monotonic() - done_at > GRACE_SECONDS:
                        break
                if time.monotonic() > deadline:
                    terminate.set()
                    break
                time.sleep(0.5)
            if process.poll() is None:
                _kill_group(process)

        watcher = threading.Thread(target=_watcher, daemon=True)
        watcher.start()
        process.wait()
        watcher.join(timeout=10)
        returncode = process.returncode
        timed_out = terminate.is_set()

    elapsed = round(time.perf_counter() - started, 2)
    output = _read_tail(out_path)
    stderr = _read_tail(err_path)
    return {
        "command": describe_command(argv, api_key),
        "returncode": returncode,
        "timed_out": timed_out,
        "submitted_marker": bool(episode is not None and getattr(episode, "submitted", False)),
        "elapsed_seconds": elapsed,
        "stdout_tail": output[-1200:],
        "stderr_tail": stderr[-600:],
    }


def _read_tail(path: Path, limit: int = 200_000) -> str:
    if not path.is_file():
        return ""
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return data[-limit:]


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate the harness and any children it spawned."""
    if os.name == "posix":
        import signal

        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            process.terminate()
    else:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )


def run(
    *,
    harness_names: list[str],
    limit: int,
    tasks_dir: Path,
    artifact: Path,
    timeout: int,
    max_steps: int,
) -> dict[str, Any]:
    api_key = _api_key()
    if not api_key:
        raise SystemExit("no credential found; set HEALTHENV_API_KEY or authenticate codex/pi first")

    task_paths = sorted(tasks_dir.glob("*.json"))
    if not task_paths:
        raise SystemExit(f"no compiled tasks in {tasks_dir}")
    tasks = [load_task(path) for path in task_paths]
    sample = _stratified_sample(tasks, limit)

    specs = harness_specs()
    unknown = [name for name in harness_names if name not in specs]
    if unknown:
        raise SystemExit(f"unknown harness(es): {', '.join(unknown)}")

    workdir = ROOT / "generated" / "harness_runs"
    workdir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for name in harness_names:
        spec = specs[name]
        for index, task in enumerate(sample):
            tool_server = ToolServer(task, max_steps=max_steps)
            cwd = workdir / f"{name}-{index:03d}"
            cwd.mkdir(parents=True, exist_ok=True)
            try:
                prompt = build_prompt(tool_server.url)
                attempt = _run_harness(
                    spec,
                    prompt=prompt,
                    cwd=cwd,
                    api_key=api_key,
                    timeout=timeout,
                    episode=tool_server.episode,
                )
                score = tool_server.episode.score()
            finally:
                tool_server.close()
            record = {
                "harness": name,
                "harness_display": spec.display_name,
                "vendor": spec.vendor,
                "task_id": task.task_id,
                "surface": str(task.source.get("surface", "timeline")),
                "category": str(task.source.get("category", "unknown")),
                "required_status": str(task.verifier.get("required_status", "review")),
                "evidence_count": len(task.verifier.get("required_evidence_ids", [])),
                "record_count": len(task.records),
                "gold_match": False,  # filled from the offline score below
                **score,
                **attempt,
            }
            record["gold_match"] = record["strict_success"]
            records.append(record)
            print(
                f"[{name}] {task.task_id} surface={record['surface']} "
                f"strict={record['strict_success']} score={record['score']} "
                f"steps={record['steps']} rc={attempt['returncode']} "
                f"{'TIMEOUT' if attempt['timed_out'] else ''}",
                flush=True,
            )

    summary: dict[str, Any] = {
        "schema_version": "0.1",
        "provider": "tierflow",
        "model": "tierflow_pro",
        "endpoint": DEFAULT_BASE_URL,
        "timeout_seconds": timeout,
        "max_steps": max_steps,
        "sampled_tasks": [task.task_id for task in sample],
        "harnesses": {},
        "records": records,
    }
    for name in harness_names:
        rows = [row for row in records if row["harness"] == name]
        if not rows:
            continue
        summary["harnesses"][name] = {
            "display_name": rows[0]["harness_display"],
            "vendor": rows[0]["vendor"],
            "episodes": len(rows),
            "strict_successes": sum(1 for row in rows if row["strict_success"]),
            "strict_success_rate": round(sum(1 for row in rows if row["strict_success"]) / len(rows), 4),
            "mean_score": round(sum(row["score"] for row in rows) / len(rows), 4),
            "submissions": sum(1 for row in rows if row["steps"] > 0 and "submit" in row["tool_calls"]),
            "timeouts": sum(1 for row in rows if row["timed_out"]),
            "mean_steps": round(sum(row["steps"] for row in rows) / len(rows), 2),
            "mean_elapsed_seconds": round(sum(row["elapsed_seconds"] for row in rows) / len(rows), 2),
            "failed_checks": _check_histogram(rows),
            "by_surface": _group_rate(rows, "surface"),
            "by_status": _group_rate(rows, "required_status"),
            "by_category": _group_rate(rows, "category"),
        }
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def _check_histogram(rows: list[dict[str, Any]]) -> dict[str, int]:
    histogram: dict[str, int] = {}
    for row in rows:
        for check in row["checks"]:
            histogram[check] = histogram.get(check, 0) + 1
    return dict(sorted(histogram.items()))


def _group_rate(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row[key]), []).append(row)
    return {
        name: {
            "episodes": len(bucket),
            "strict_successes": sum(1 for row in bucket if row["strict_success"]),
            "success_rate": round(sum(1 for row in bucket if row["strict_success"]) / len(bucket), 4),
        }
        for name, bucket in sorted(groups.items())
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harnesses", default="pi,codex,deepseek")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max-steps", type=int, default=60)
    parser.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS_DIR)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    args = parser.parse_args()

    summary = run(
        harness_names=[name.strip() for name in args.harnesses.split(",") if name.strip()],
        limit=args.limit,
        tasks_dir=args.tasks_dir,
        artifact=args.artifact,
        timeout=args.timeout,
        max_steps=args.max_steps,
    )
    compact = {
        "schema_version": summary["schema_version"],
        "model": summary["model"],
        "harnesses": summary["harnesses"],
    }
    print(json.dumps(compact, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
