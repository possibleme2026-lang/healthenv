"""Command-line entry point for compilation, serving, and verification."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .compiler import compile_seed, compile_seed_file
from .lifeagent import import_lifeagent_item
from .llm import OpenAICompatibleClient
from .seedgen import generate_seeds, write_seed_file
from .server import load_task, serve
from .verifier import verify_state


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="healthenv")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate-seeds", help="synthesize QA seeds at scale")
    generate_parser.add_argument("--count", type=int, default=1200)
    generate_parser.add_argument("--seed", type=int, default=20261012)
    generate_parser.add_argument("--output", "-o", required=True)

    compile_parser = subparsers.add_parser("compile", help="compile QA JSONL into task specs")
    compile_parser.add_argument("input")
    compile_parser.add_argument("--output", "-o", required=True)
    compile_parser.add_argument("--benchmark", default="LifeAgentBench-style")
    compile_parser.add_argument("--llm", action="store_true", help="use TierFlow for instruction planning")

    import_parser = subparsers.add_parser(
        "import-lifeagent", help="compile one local LifeAgentBench JSONL item without redistributing it"
    )
    import_parser.add_argument("input")
    import_parser.add_argument("--line", type=int, default=1)
    import_parser.add_argument("--output", "-o", required=True)
    import_parser.add_argument("--llm", action="store_true")

    serve_parser = subparsers.add_parser("serve", help="serve one compiled browser task")
    serve_parser.add_argument("task")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)

    verify_parser = subparsers.add_parser("verify", help="verify a saved environment state")
    verify_parser.add_argument("task")
    verify_parser.add_argument("state")

    oracle_parser = subparsers.add_parser("oracle", help="emit the deterministic oracle state")
    oracle_parser.add_argument("task")
    oracle_parser.add_argument("--output", "-o")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "generate-seeds":
        written = write_seed_file(generate_seeds(args.count, master_seed=args.seed), args.output)
        print(f"wrote {written} seeds to {args.output}")
        return 0
    if args.command == "compile":
        client = OpenAICompatibleClient.from_env() if args.llm else None
        outputs = compile_seed_file(
            args.input,
            args.output,
            llm_client=client,
            benchmark_name=args.benchmark,
        )
        for output in outputs:
            print(output)
        return 0
    if args.command == "import-lifeagent":
        client = OpenAICompatibleClient.from_env() if args.llm else None
        seed = import_lifeagent_item(args.input, args.line)
        task = compile_seed(seed, llm_client=client, benchmark_name="LifeAgentBench")
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(output)
        return 0
    if args.command == "serve":
        serve(args.task, args.host, args.port)
        return 0
    if args.command == "verify":
        task = load_task(args.task)
        state = json.loads(Path(args.state).read_text(encoding="utf-8"))
        print(json.dumps(verify_state(task, state).to_dict(), indent=2))
        return 0
    if args.command == "oracle":
        task = load_task(args.task)
        state = {
            "selected_record_ids": task.verifier["required_evidence_ids"],
            "note": " ".join(task.verifier["note_must_include"]),
            "status": task.verifier["required_status"],
            "submitted": True,
            "forbidden_edits": [],
            "audit_log": [],
        }
        rendered = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    raise AssertionError("unreachable")
