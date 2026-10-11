"""Compile all demo seeds and prove positive and negative verifier behavior."""

from __future__ import annotations

import json
from pathlib import Path

from healthenv.compiler import compile_seed_file
from healthenv.server import load_task
from healthenv.verifier import verify_state

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "data" / "seeds" / "lifeagentbench_demo.jsonl"
OUTPUT = ROOT / "generated" / "demo"
RESULTS = ROOT / "artifacts" / "demo_results.json"


def main() -> None:
    outputs = compile_seed_file(SEEDS, OUTPUT)
    runs = []
    for output in outputs:
        task = load_task(output)
        oracle = {
            "selected_record_ids": task.verifier["required_evidence_ids"],
            "note": " ".join(task.verifier["note_must_include"]),
            "status": task.verifier["required_status"],
            "submitted": True,
            "forbidden_edits": [],
        }
        positive = verify_state(task, oracle)
        negative_state = dict(oracle, selected_record_ids=[])
        negative = verify_state(task, negative_state)
        runs.append(
            {
                "task_id": task.task_id,
                "category": task.source["category"],
                "positive_strict_success": positive.strict_success,
                "positive_score": positive.score,
                "negative_strict_success": negative.strict_success,
                "negative_score": negative.score,
            }
        )
    summary = {
        "schema_version": "0.1",
        "task_count": len(runs),
        "positive_passes": sum(run["positive_strict_success"] for run in runs),
        "negative_rejections": sum(not run["negative_strict_success"] for run in runs),
        "runs": runs,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
