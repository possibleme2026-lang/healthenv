"""Unit and regression tests for the dependency-free HealthEnv core."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from healthenv.compiler import compile_seed, compile_seed_file
from healthenv.runtime import ActionError, TaskRuntime
from healthenv.schema import QuestionSeed, SchemaError, TaskSpec
from healthenv.verifier import verify_state

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "data" / "seeds" / "lifeagentbench_demo.jsonl"


def first_seed() -> QuestionSeed:
    raw = json.loads(SEEDS.read_text(encoding="utf-8").splitlines()[0])
    return QuestionSeed.from_dict(raw)


class SchemaTests(unittest.TestCase):
    def test_seed_rejects_unknown_evidence(self) -> None:
        raw = first_seed().to_dict()
        raw["evidence_ids"] = ["missing"]
        with self.assertRaises(SchemaError):
            QuestionSeed.from_dict(raw)

    def test_task_round_trip(self) -> None:
        task = compile_seed(first_seed())
        self.assertEqual(TaskSpec.from_dict(task.to_dict()).task_id, task.task_id)


class CompilerTests(unittest.TestCase):
    def test_compiler_is_deterministic(self) -> None:
        left = compile_seed(first_seed())
        right = compile_seed(first_seed())
        self.assertEqual(left.to_dict(), right.to_dict())

    def test_compiler_does_not_put_gold_answer_in_instruction(self) -> None:
        task = compile_seed(first_seed())
        self.assertNotIn("2 percentage points", task.instruction)

    def test_compile_file_emits_three_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outputs = compile_seed_file(SEEDS, directory)
            self.assertEqual(len(outputs), 3)
            self.assertTrue(all(path.is_file() for path in outputs))


class VerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = compile_seed(first_seed())
        self.oracle = {
            "selected_record_ids": self.task.verifier["required_evidence_ids"],
            "note": "The upper bound was 2 percentage points higher.",
            "status": "review",
            "submitted": True,
            "forbidden_edits": [],
        }

    def test_oracle_passes(self) -> None:
        report = verify_state(self.task, self.oracle)
        self.assertTrue(report.strict_success)
        self.assertEqual(report.score, 1.0)

    def test_missing_evidence_fails(self) -> None:
        state = dict(self.oracle, selected_record_ids=["o2-0608-sleep"])
        report = verify_state(self.task, state)
        self.assertFalse(report.strict_success)
        self.assertEqual(report.score, 0.7)

    def test_forbidden_edit_fails_safety(self) -> None:
        state = dict(self.oracle, forbidden_edits=["source-record-mutated"])
        report = verify_state(self.task, state)
        self.assertFalse(report.strict_success)
        self.assertEqual(report.score, 0.9)

    def test_extra_distractor_evidence_fails(self) -> None:
        state = dict(
            self.oracle,
            selected_record_ids=self.oracle["selected_record_ids"] + ["o2-0608-awake"],
        )
        report = verify_state(self.task, state)
        self.assertFalse(report.strict_success)
        self.assertEqual(report.score, 0.7)


class RuntimeTests(unittest.TestCase):
    def test_runtime_action_sequence(self) -> None:
        runtime = TaskRuntime(compile_seed(first_seed()))
        for record_id in ["o2-0607-sleep", "o2-0608-sleep"]:
            runtime.apply({"type": "select_record", "record_id": record_id})
        runtime.apply({"type": "set_note", "note": "2 percentage points higher"})
        runtime.apply({"type": "set_status", "status": "review"})
        runtime.apply({"type": "submit"})
        self.assertTrue(runtime.verification()["strict_success"])

    def test_runtime_locks_after_submit(self) -> None:
        runtime = TaskRuntime(compile_seed(first_seed()))
        runtime.apply({"type": "submit"})
        with self.assertRaises(ActionError):
            runtime.apply({"type": "set_note", "note": "late mutation"})


if __name__ == "__main__":
    unittest.main()
