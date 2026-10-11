"""Regression tests for deterministic seed synthesis at scale."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from healthenv.compiler import compile_seed
from healthenv.runtime import TaskRuntime
from healthenv.seedgen import METRICS, SKILLS, generate_seeds
from healthenv.verifier import verify_state

COUNT = 84  # 12 per reasoning skill


class SeedGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.seeds = generate_seeds(COUNT)

    def test_generates_requested_count(self) -> None:
        self.assertEqual(len(self.seeds), COUNT)

    def test_is_deterministic(self) -> None:
        first = [seed.to_dict() for seed in generate_seeds(12, master_seed=7)]
        second = [seed.to_dict() for seed in generate_seeds(12, master_seed=7)]
        self.assertEqual(first, second)
        self.assertNotEqual(first, [seed.to_dict() for seed in generate_seeds(12, master_seed=8)])

    def test_rejects_non_positive_count(self) -> None:
        with self.assertRaises(ValueError):
            generate_seeds(0)

    def test_every_seed_has_evidence_and_at_least_one_distractor(self) -> None:
        for seed in self.seeds:
            with self.subTest(seed=seed.seed_id):
                record_ids = {str(record["id"]) for record in seed.records}
                self.assertTrue(seed.evidence_ids, "evidence must not be empty")
                self.assertTrue(set(seed.evidence_ids) <= record_ids)
                self.assertGreaterEqual(len(record_ids) - len(seed.evidence_ids), 1)

    def test_covers_every_skill(self) -> None:
        skills = Counter(seed.category for seed in self.seeds)
        self.assertEqual(set(skills), set(SKILLS))
        self.assertTrue(all(count == COUNT // len(SKILLS) for count in skills.values()))

    def test_covers_every_metric_domain(self) -> None:
        used = {str(seed.metadata["metric"]).split("+")[0] for seed in self.seeds}
        self.assertTrue({metric.key for metric in METRICS} <= used)

    def test_questions_and_answers_are_varied(self) -> None:
        self.assertGreaterEqual(len({seed.question for seed in self.seeds}), int(COUNT * 0.9))
        self.assertGreaterEqual(len({seed.answer for seed in self.seeds}), int(COUNT * 0.4))

    def test_seed_ids_are_unique(self) -> None:
        self.assertEqual(len({seed.seed_id for seed in self.seeds}), COUNT)


class ScaleCompilationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.seeds = generate_seeds(COUNT)
        cls.tasks = [compile_seed(seed, benchmark_name="HealthEnv-Scale") for seed in cls.seeds]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_task_ids_are_unique(self) -> None:
        self.assertEqual(len({task.task_id for task in self.tasks}), COUNT)

    def test_oracle_passes_for_every_task(self) -> None:
        failures = []
        for task in self.tasks:
            runtime = TaskRuntime(task)
            for record_id in task.verifier["required_evidence_ids"]:
                runtime.apply({"type": "select_record", "record_id": record_id})
            runtime.apply({"type": "set_note", "note": " ".join(task.verifier["note_must_include"])})
            runtime.apply({"type": "set_status", "status": task.verifier["required_status"]})
            runtime.apply({"type": "submit"})
            report = runtime.verification()
            if not report["strict_success"]:
                failures.append((task.task_id, report["score"]))
        self.assertEqual(failures, [])

    def test_distractors_matter(self) -> None:
        """Selecting every record must fail, otherwise distractors are decorative."""
        failures = []
        for task in self.tasks:
            state = {
                "selected_record_ids": [str(record["id"]) for record in task.records],
                "note": " ".join(task.verifier["note_must_include"]),
                "status": task.verifier["required_status"],
                "submitted": True,
                "forbidden_edits": [],
            }
            if verify_state(task, state).strict_success:
                failures.append(task.task_id)
        self.assertEqual(failures, [])

    def test_ungrounded_note_is_rejected(self) -> None:
        failures = []
        for task in self.tasks:
            state = {
                "selected_record_ids": task.verifier["required_evidence_ids"],
                "note": "No conclusion recorded.",
                "status": task.verifier["required_status"],
                "submitted": True,
                "forbidden_edits": [],
            }
            if verify_state(task, state).strict_success:
                failures.append(task.task_id)
        self.assertEqual(failures, [])

    def test_wrong_priority_is_rejected(self) -> None:
        failures = []
        for task in self.tasks:
            required = str(task.verifier["required_status"])
            wrong = "routine" if required != "routine" else "urgent"
            state = {
                "selected_record_ids": task.verifier["required_evidence_ids"],
                "note": " ".join(task.verifier["note_must_include"]),
                "status": wrong,
                "submitted": True,
                "forbidden_edits": [],
            }
            if verify_state(task, state).strict_success:
                failures.append(task.task_id)
        self.assertEqual(failures, [])

    def test_instruction_states_the_required_priority(self) -> None:
        for seed, task in zip(self.seeds, self.tasks, strict=True):
            with self.subTest(task=task.task_id):
                required = str(seed.metadata["required_status"])
                self.assertIn(required.capitalize(), task.instruction)

    def test_tasks_round_trip_through_json(self) -> None:
        for task in self.tasks[:10]:
            raw = json.loads(json.dumps(task.to_dict()))
            self.assertEqual(raw["task_id"], task.task_id)


class NoteTermMatchingTests(unittest.TestCase):
    def test_substring_does_not_satisfy_a_numeric_term(self) -> None:
        """A note that only says 2024 must not satisfy a required term of "2"."""
        seeds = generate_seeds(7, master_seed=99)
        task = compile_seed(seeds[0], benchmark_name="HealthEnv-Scale")
        base = {
            "selected_record_ids": task.verifier["required_evidence_ids"],
            "status": task.verifier["required_status"],
            "submitted": True,
            "forbidden_edits": [],
        }
        report = verify_state(task, dict(base, note="Seen on 2024-05-03 only."))
        self.assertFalse(report.strict_success)
        oracle = verify_state(task, dict(base, note=" ".join(task.verifier["note_must_include"])))
        self.assertTrue(oracle.strict_success)


if __name__ == "__main__":
    unittest.main()
