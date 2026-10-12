"""Generate, compile, and stress-test HealthEnv at benchmark scale.

For every generated environment the pipeline proves five things:

1. an oracle trajectory reaches strict success (the task is solvable);
2. selecting nothing is rejected;
3. selecting every record is rejected (so distractors actually matter);
4. an ungrounded note is rejected;
5. the wrong workflow priority is rejected.

It also reports diversity statistics, because "1200 environments" is only
interesting if the instances differ from each other.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from healthenv.compiler import compile_seed_file
from healthenv.schema import QuestionSeed
from healthenv.seedgen import generate_seeds, write_seed_file
from healthenv.server import load_task
from healthenv.verifier import verify_state

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COUNT = 1200
DEFAULT_MASTER_SEED = 20261012


def _skeleton(task: Any) -> tuple[str, str, int, int, str]:
    source = task.source
    evidence = len(task.verifier["required_evidence_ids"])
    distractors = len(task.records) - evidence
    return (
        str(source["category"]),
        str(task.generation.get("mode", "deterministic")),
        evidence,
        distractors,
        str(task.verifier.get("required_status", "review")),
    )


def _negative_states(task: Any) -> dict[str, dict[str, Any]]:
    evidence = list(task.verifier["required_evidence_ids"])
    terms = list(task.verifier["note_must_include"])
    status = str(task.verifier["required_status"])
    oracle: dict[str, Any] = {
        "selected_record_ids": evidence,
        "note": " ".join(terms),
        "status": status,
        "submitted": True,
        "forbidden_edits": [],
    }
    all_ids = [str(record["id"]) for record in task.records]
    wrong_status = "routine" if status != "routine" else "urgent"
    return {
        "oracle": oracle,
        "empty_evidence": dict(oracle, selected_record_ids=[]),
        "all_records": dict(oracle, selected_record_ids=all_ids),
        "ungrounded_note": dict(oracle, note="No conclusion recorded."),
        "wrong_status": dict(oracle, status=wrong_status),
    }


def run(
    count: int = DEFAULT_COUNT,
    *,
    master_seed: int = DEFAULT_MASTER_SEED,
    seeds_path: Path | None = None,
    output_dir: Path | None = None,
    results_path: Path | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    seeds_path = seeds_path or (ROOT / "data" / "seeds" / f"health_scale_{count}.jsonl")
    output_dir = output_dir or (ROOT / "generated" / "scale")
    results_path = results_path or (ROOT / "artifacts" / "scale_results.json")

    seeds: list[QuestionSeed] = generate_seeds(count, master_seed=master_seed)
    written = write_seed_file(seeds, str(seeds_path))
    outputs = compile_seed_file(seeds_path, output_dir, benchmark_name="HealthEnv-Scale")

    positives = 0
    negatives = Counter()
    per_task: list[dict[str, Any]] = []
    skeletons: Counter[tuple[str, str, int, int, str]] = Counter()
    answers: Counter[str] = Counter()
    questions: Counter[str] = Counter()
    question_answer_pairs: set[tuple[str, str]] = set()
    categories: Counter[str] = Counter()
    metrics: Counter[str] = Counter()
    answer_types: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    surfaces: Counter[str] = Counter()
    record_counts: Counter[int] = Counter()
    task_ids: set[str] = set()
    structural_errors: list[str] = []

    for index, seed in enumerate(seeds):
        task = load_task(outputs[index])
        task_ids.add(task.task_id)
        categories[str(task.source["category"])] += 1
        metrics[str(seed.metadata.get("metric", "unknown"))] += 1
        answer_types[str(seed.metadata.get("answer_type", "unknown"))] += 1
        statuses[str(task.verifier["required_status"])] += 1
        surfaces[str(task.source.get("surface", "timeline"))] += 1
        record_counts[len(task.records)] += 1
        answers[seed.answer] += 1
        questions[seed.question] += 1
        question_answer_pairs.add((seed.question, seed.answer))
        skeletons[_skeleton(task)] += 1

        evidence = set(task.verifier["required_evidence_ids"])
        record_ids = {str(record["id"]) for record in task.records}
        if not evidence:
            structural_errors.append(f"{task.task_id}: no evidence records")
        if not evidence <= record_ids:
            structural_errors.append(f"{task.task_id}: evidence outside records")
        if len(record_ids) - len(evidence) < 1:
            structural_errors.append(f"{task.task_id}: no distractor record")

        states = _negative_states(task)
        positive = verify_state(task, states["oracle"])
        positives += int(positive.strict_success)
        row: dict[str, Any] = {
            "task_id": task.task_id,
            "category": task.source["category"],
            "answer_type": seed.metadata.get("answer_type"),
            "positive_strict_success": positive.strict_success,
            "positive_score": positive.score,
        }
        for name in ("empty_evidence", "all_records", "ungrounded_note", "wrong_status"):
            report = verify_state(task, states[name])
            rejected = not report.strict_success
            negatives[name] += int(rejected)
            row[f"{name}_rejected"] = rejected
            row[f"{name}_score"] = report.score
        per_task.append(row)

    elapsed = round(time.perf_counter() - started, 3)
    summary: dict[str, Any] = {
        "schema_version": "0.1",
        "generator": "healthenv.seedgen/0.1",
        "master_seed": master_seed,
        "requested_count": count,
        "seeds_written": written,
        "tasks_compiled": len(outputs),
        "unique_task_ids": len(task_ids),
        # POSIX separators keep the report identical across Windows and Linux
        "seed_file": seeds_path.relative_to(ROOT).as_posix(),
        "output_dir": output_dir.relative_to(ROOT).as_posix(),
        "oracle_strict_passes": positives,
        "negative_rejections": dict(sorted(negatives.items())),
        "structural_errors": structural_errors,
        "elapsed_seconds": elapsed,
        "diversity": {
            "unique_questions": len(questions),
            "unique_answers": len(answers),
            "unique_question_answer_pairs": len(question_answer_pairs),
            "unique_skeletons": len(skeletons),
            "skeleton_note": (
                "skeleton = (category, generation mode, evidence count, distractor count, "
                "required status); instances outnumber skeletons by design"
            ),
            "categories": dict(sorted(categories.items())),
            "metrics": dict(sorted(metrics.items())),
            "answer_types": dict(sorted(answer_types.items())),
            "required_status": dict(sorted(statuses.items())),
            "surfaces": dict(sorted(surfaces.items())),
            "surface_note": (
                "surface selects the rendered health-software layout (timeline / vitals "
                "dashboard / clinical ledger); it never changes evidence, gold answer, or verifier"
            ),
            # keys are stringified so the report compares equal after a JSON round-trip
            "records_per_task": {str(key): value for key, value in sorted(record_counts.items())},
        },
        "runs": per_task,
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def _comparable(summary: dict[str, Any]) -> dict[str, Any]:
    """Report payload minus timing, so two runs can be compared exactly."""
    clone = dict(summary)
    clone.pop("elapsed_seconds", None)
    return clone


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and stress-test HealthEnv at scale")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_MASTER_SEED)
    parser.add_argument("--min-count", type=int, default=1000)
    parser.add_argument(
        "--check",
        action="store_true",
        help="also require the regenerated report to match the checked-in one",
    )
    args = parser.parse_args()

    results_path = ROOT / "artifacts" / "scale_results.json"
    previous: dict[str, Any] | None = None
    if args.check:
        if not results_path.exists():
            print("FAIL: no checked-in scale report to compare against")
            return 1
        previous = json.loads(results_path.read_text(encoding="utf-8"))

    summary = run(args.count, master_seed=args.seed, results_path=results_path)
    compact = dict(summary)
    compact.pop("runs")
    print(json.dumps(compact, indent=2))

    failures: list[str] = []
    if summary["tasks_compiled"] < args.min_count:
        failures.append(f"compiled {summary['tasks_compiled']} tasks, expected >= {args.min_count}")
    if summary["unique_task_ids"] != summary["tasks_compiled"]:
        failures.append("duplicate task ids detected")
    if summary["oracle_strict_passes"] != summary["tasks_compiled"]:
        failures.append("some oracle trajectories did not reach strict success")
    for name, rejected in summary["negative_rejections"].items():
        if rejected != summary["tasks_compiled"]:
            failures.append(
                f"negative control {name} rejected only {rejected} of {summary['tasks_compiled']}"
            )
    if summary["structural_errors"]:
        failures.append(f"structural errors: {summary['structural_errors'][:5]}")
    if args.check:
        if previous is None or _comparable(previous) != _comparable(summary):
            failures.append("regenerated scale report does not match the checked-in one")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print(f"OK: {summary['tasks_compiled']} environments, all controls passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
