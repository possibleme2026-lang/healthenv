"""Tests for the agent-facing tool surface and its information barrier.

The barrier is the load-bearing property here: if an evaluated agent can read
the verifier, the benchmark measures oracle-following rather than reasoning.
These tests assert the barrier from the outside, over HTTP, so they exercise the
same path a harness uses.
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from healthenv.agentenv import Episode, serve_episode
from healthenv.compiler import compile_seed
from healthenv.harness import build_prompt, harness_specs
from healthenv.sampling import stratified_sample
from healthenv.schema import QuestionSeed
from healthenv.server import load_task


def _task() -> object:
    seed = QuestionSeed.from_dict(
        {
            "seed_id": "agent-barrier-001",
            "participant_id": "HENV-9001",
            "question": "How many hours longer was sleep on 2024-03-02 than on 2024-03-01?",
            "answer": "1.2 hours",
            "category": "temporal-aggregation",
            "records": [
                {
                    "id": "sleep-0301",
                    "date": "2024-03-01",
                    "type": "sleep duration",
                    "value": 6.4,
                    "unit": "hours",
                    "detail": "Daily measurement",
                },
                {
                    "id": "sleep-0302",
                    "date": "2024-03-02",
                    "type": "sleep duration",
                    "value": 7.6,
                    "unit": "hours",
                    "detail": "Daily measurement",
                },
                {
                    "id": "steps-0302",
                    "date": "2024-03-02",
                    "type": "step count",
                    "value": 8200,
                    "unit": "steps",
                    "detail": "Different metric",
                },
            ],
            "evidence_ids": ["sleep-0301", "sleep-0302"],
            "metadata": {"required_status": "review", "note_must_include": ["1.2", "hours"]},
        }
    )
    return compile_seed(seed)


class TestInformationBarrier(unittest.TestCase):
    def setUp(self) -> None:
        self.server, self.episode = serve_episode(_task(), port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{int(self.server.server_address[1])}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _get(self, path: str) -> dict[str, object]:
        with urllib.request.urlopen(f"{self.base}{path}", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))  # type: ignore[no-any-return]

    def _get_tool(self, query: str) -> dict[str, object]:
        """Invoke a tool the way the prompt teaches: GET with query arguments."""
        return self._get(f"/tool?{query}")

    def _call(self, tool: str, **args: object) -> dict[str, object]:
        request = urllib.request.Request(
            f"{self.base}/tool",
            data=json.dumps({"tool": tool, "args": args}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))  # type: ignore[no-any-return]

    def test_manifest_lists_tools_without_gold(self) -> None:
        manifest = self._get("/manifest")
        names = {tool["name"] for tool in manifest["tools"]}  # type: ignore[union-attr,index]
        self.assertEqual(
            names,
            {"get_task", "list_records", "read_state", "select_record", "set_note", "set_status", "submit"},
        )
        blob = json.dumps(manifest)
        self.assertNotIn("evidence_ids", blob)
        self.assertNotIn("required_evidence", blob)

    def test_get_task_hides_category_and_surface(self) -> None:
        task = self._call("get_task")
        self.assertNotIn("source", task)
        blob = json.dumps(task)
        # the reasoning skill and the rendered surface are hints an agent must not receive
        self.assertNotIn("temporal-aggregation", blob)
        self.assertNotIn("surface", blob)
        self.assertIn("records", task)

    def test_submit_returns_no_verifier_signal(self) -> None:
        self._call("select_record", record_id="sleep-0301", selected=True)
        response = self._call("submit")
        blob = json.dumps(response)
        self.assertTrue(response["submitted"])
        self.assertNotIn("verification", blob)
        self.assertNotIn("strict_success", blob)
        self.assertNotIn("checks", blob)
        self.assertNotIn("score", blob)

    def test_verify_endpoint_is_not_reachable_through_the_tool_server(self) -> None:
        for path in ("/api/verify", "/api/task", "/api/state"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f"{self.base}{path}", timeout=10)
            self.assertEqual(caught.exception.code, 404)

    def test_actions_are_refused_after_submit(self) -> None:
        self._call("submit")
        response = self._call("select_record", record_id="sleep-0301", selected=True)
        self.assertFalse(response["ok"])
        self.assertIn("already submitted", str(response["error"]))

    def test_get_transport_matches_post_transport(self) -> None:
        """The documented GET call and the POST alias must be equivalent.

        The prompt teaches GET because a JSON body is mangled by PowerShell 5.1,
        which ``codex`` and ``dsh`` drive on Windows. If the two transports ever
        diverge, a harness comparison starts measuring shell quoting.
        """
        by_get = self._get_tool("tool=get_task")
        by_post = self._call("get_task")
        self.assertEqual(by_get, by_post)
        self.assertIn("records", by_get)

    def test_get_transport_encodes_spaces_and_punctuation(self) -> None:
        note = "LVEF 38% on 2026-03-04; recommend cardiology review"
        quoted = urllib.parse.quote(note, safe="")
        response = self._get_tool(f"tool=set_note&note={quoted}")
        self.assertTrue(response["ok"])
        state = response["state"]
        self.assertEqual(state["note"], note)  # type: ignore[index]

    def test_query_values_are_coerced_to_the_declared_type(self) -> None:
        """`selected=false` arrives as text; it must not be read as truthy."""
        self._get_tool("tool=select_record&record_id=sleep-0301&selected=true")
        state = self._call("read_state")
        self.assertEqual(state["selected_record_ids"], ["sleep-0301"])

        self._get_tool("tool=select_record&record_id=sleep-0301&selected=false")
        state = self._call("read_state")
        self.assertEqual(state["selected_record_ids"], [])

    def test_get_tool_missing_name_is_rejected(self) -> None:
        response = self._get_tool("record_id=sleep-0301")
        self.assertFalse(response["ok"])
        self.assertIn("unknown tool", str(response["error"]))


class TestEpisode(unittest.TestCase):
    def test_oracle_trajectory_scores_strict_success(self) -> None:
        episode = Episode(_task())
        task = episode.task
        for record_id in task.verifier["required_evidence_ids"]:
            episode.call("select_record", {"record_id": record_id, "selected": True})
        episode.call("set_note", {"note": "1.2 hours longer"})
        episode.call("set_status", {"status": task.verifier["required_status"]})
        episode.call("submit", {})
        score = episode.score()
        self.assertTrue(score["strict_success"])
        self.assertEqual(score["score"], 1.0)
        self.assertEqual(score["checks"], [])
        self.assertIn("submit", score["tool_calls"])

    def test_selecting_every_record_is_penalized(self) -> None:
        episode = Episode(_task())
        for record in episode.task.records:
            episode.call("select_record", {"record_id": str(record["id"]), "selected": True})
        episode.call("set_note", {"note": "1.2 hours longer"})
        episode.call("set_status", {"status": "review"})
        episode.call("submit", {})
        score = episode.score()
        self.assertFalse(score["strict_success"])
        self.assertIn("evidence_selection", score["checks"])
        self.assertEqual(score["score"], 0.7)

    def test_step_budget_is_enforced(self) -> None:
        episode = Episode(_task(), max_steps=3)
        for _ in range(3):
            # observe tools return the payload itself, not an ok envelope
            self.assertIn("note", episode.call("read_state", {}))
        response = episode.call("read_state", {})
        self.assertFalse(response["ok"])
        self.assertIn("budget", str(response["error"]))

    def test_unknown_tool_is_rejected(self) -> None:
        episode = Episode(_task())
        response = episode.call("drop_table", {})
        self.assertFalse(response["ok"])
        self.assertIn("unknown tool", str(response["error"]))


class TestHarnessPrompt(unittest.TestCase):
    def test_prompt_leaks_no_gold(self) -> None:
        prompt = build_prompt("http://127.0.0.1:1234")
        self.assertIn("127.0.0.1:1234", prompt)
        self.assertIn("submit", prompt)
        for leaked in ("evidence_ids", "required_evidence", "strict_success", "gold"):
            self.assertNotIn(leaked, prompt)

    def test_prompt_teaches_a_shell_agnostic_call(self) -> None:
        """The prompt must not teach the JSON-body form.

        PowerShell 5.1, which codex and dsh drive on Windows, strips the inner
        double quotes from an argv JSON body before the native exe sees it, so a
        harness would be scored on shell quoting rather than on reasoning.
        """
        prompt = build_prompt("http://127.0.0.1:1234")
        self.assertIn("-G", prompt)
        self.assertIn("--data-urlencode", prompt)
        self.assertNotIn('{"tool"', prompt)

    def test_three_harnesses_are_declared_and_point_at_one_model(self) -> None:
        specs = harness_specs()
        self.assertEqual(sorted(specs), ["codex", "deepseek", "pi"])
        for name, spec in specs.items():
            # the model may be declared on the command line or, for dsh, in its patch
            declared = " ".join(spec.build_command("x", "/tmp")) + " ".join(spec.setup_files.values())
            self.assertIn("tierflow_pro", declared, name)
            self.assertIn(spec.prompt_transport, {"file", "stdin", "pointer"})

    def test_no_harness_receives_the_prompt_in_multiline_argv(self) -> None:
        """Every harness must be able to recover the whole prompt.

        A multi-line argv prompt is truncated to its first line on Windows, so a
        harness either inlines the file itself, reads it from stdin, or is handed
        a one-line pointer to it.
        """
        specs = harness_specs()
        multiline = "LINE1\nLINE2\nLINE3"
        for name, spec in specs.items():
            argv = spec.build_command(multiline, "/tmp/work")
            joined = " ".join(argv)
            self.assertNotIn("LINE2", joined, f"{name} passes the prompt through argv")
            if spec.prompt_transport == "file":
                self.assertTrue(any(arg.startswith("@") for arg in argv), name)
            elif spec.prompt_transport == "stdin":
                self.assertIn("-", argv, name)
            else:
                self.assertTrue(
                    any("PROMPT" in arg and "LINE" not in arg for arg in argv), name
                )


class TestPromptTransports(unittest.TestCase):
    def test_prompt_file_is_written_verbatim(self) -> None:
        from healthenv.harness import PROMPT_FILENAME, prompt_file

        text = "LINE1\nLINE2\nLINE3"
        self.assertEqual(prompt_file(text), text)
        self.assertEqual(PROMPT_FILENAME, "PROMPT.txt")

    def test_pointer_names_the_prompt_file(self) -> None:
        from healthenv.harness import PROMPT_FILENAME, prompt_pointer

        pointer = prompt_pointer()
        self.assertIn(PROMPT_FILENAME, pointer)
        self.assertNotIn("\n", pointer)


class TestCompiledTaskExposesSurface(unittest.TestCase):
    def test_surface_reaches_source_but_not_agent_view(self) -> None:
        from healthenv.runtime import TaskRuntime

        seed = QuestionSeed.from_dict(
            {
                "seed_id": "surface-001",
                "participant_id": "HENV-9002",
                "question": "q",
                "answer": "1 hours",
                "category": "temporal-aggregation",
                "records": [
                    {"id": "a", "date": "2024-01-01", "type": "sleep duration", "value": 1, "unit": "hours"},
                    {"id": "b", "date": "2024-01-02", "type": "sleep duration", "value": 2, "unit": "hours"},
                ],
                "evidence_ids": ["a", "b"],
                "metadata": {"surface": "clinical-ledger"},
            }
        )
        task = compile_seed(seed)
        self.assertEqual(task.source["surface"], "clinical-ledger")
        runtime = TaskRuntime(task)
        self.assertEqual(runtime.public_task()["source"]["surface"], "clinical-ledger")
        self.assertNotIn("source", runtime.agent_task())

    def test_unknown_surface_falls_back(self) -> None:
        seed = QuestionSeed.from_dict(
            {
                "seed_id": "surface-002",
                "participant_id": "HENV-9003",
                "question": "q",
                "answer": "1 hours",
                "category": "trend-classification",
                "records": [
                    {"id": "a", "date": "2024-01-01", "type": "sleep duration", "value": 1, "unit": "hours"}
                ],
                "evidence_ids": ["a"],
                "metadata": {"surface": "not-a-real-surface"},
            }
        )
        self.assertEqual(compile_seed(seed).source["surface"], "timeline")


class TestScaleTasksCarrySurfaces(unittest.TestCase):
    def test_compiled_scale_sample_spans_all_three_surfaces(self) -> None:
        directory = Path(__file__).resolve().parents[1] / "generated" / "scale"
        if not directory.is_dir():
            self.skipTest("scale corpus not generated in this checkout")
        paths = sorted(directory.glob("*.json"))[:60]
        self.assertGreater(len(paths), 0)
        surfaces = {load_task(path).source.get("surface") for path in paths}
        self.assertTrue(surfaces <= {"timeline", "vitals-dashboard", "clinical-ledger"})


class TestFrontendContract(unittest.TestCase):
    """The browser driver and the served HTML must agree on their contract.

    Two classes of drift are guarded here. A selector the driver clicks but the
    page does not render would fail 1200 browser runs; a concurrent `act()` lets
    two change handlers race, and the first response's `syncForm()` can restore
    the textarea from a snapshot that predates the other write -- observed in the
    1200-task browser run as two episodes whose submitted note was empty
    (evidence PASS, grounded-note FAIL) while offline replay of the same actions
    reaches strict success.
    """

    @staticmethod
    def _html() -> str:
        from importlib.resources import files

        return files("healthenv.assets").joinpath("index.html").read_text(encoding="utf-8")

    def test_driver_selectors_exist_in_the_page(self) -> None:
        html = self._html()
        for selector in (
            'data-testid="record-list"',
            'data-testid="care-note"',
            'data-testid="workflow-status"',
            'data-testid="submit-task"',
            'data-testid="record-',
            'id="selectedCount"',
            'id="surfaceTag"',
            'id="result"',
        ):
            self.assertIn(selector, html, f"driver contract broken: {selector} missing")

    def test_actions_are_serialized(self) -> None:
        """`act()` must chain promises so responses are applied in send order."""
        html = self._html()
        self.assertIn("actChain", html)
        self.assertIn("actChain=actChain.then", html)

    def test_act_is_not_declared_as_a_bare_async_function(self) -> None:
        """The unserialized form is the one that races.

        A plain `async function act(...)` issues an unqueued fetch, so a note
        handler and a status handler can resolve out of order. The serialized
        form keeps `act` synchronous and returns the chained promise, which is
        what callers must use instead of assuming the write already landed.
        """
        html = self._html()
        self.assertNotIn("async function act(", html)
        self.assertIn("function act(action){", html)


class TestStratifiedSample(unittest.TestCase):
    """The sampler must not collapse onto one surface for small limits.

    The original flat round-robin sorted cells alphabetically, and every
    clinical-ledger cell outranked every timeline cell, so ``--limit 12``
    returned 12/12 ledger tasks -- a confound the paper would have inherited.
    """

    @staticmethod
    def _make(surface: str, status: str, category: str) -> QuestionSeed:
        return QuestionSeed.from_dict(
            {
                "seed_id": f"{surface}-{status}-{category}",
                "participant_id": "HENV-9500",
                "question": "Sample question?",
                "answer": "sample answer",
                "category": category,
                "records": [
                    {
                        "id": "r1",
                        "date": "2024-03-01",
                        "type": "sleep duration",
                        "value": 6.0,
                        "unit": "hours",
                        "detail": "",
                    }
                ],
                "evidence_ids": ["r1"],
                "metadata": {"required_status": status, "surface": surface},
            }
        )

    def test_small_limit_spreads_across_surfaces(self) -> None:
        sampler = _load_harness_eval()._stratified_sample

        tasks = [
            self._make(surface, status, category)
            for surface in ("clinical-ledger", "timeline", "vitals-dashboard")
            for status in ("review", "routine")
            for category in ("temporal-aggregation", "threshold-detection")
        ]
        specs = [compile_seed(seed) for seed in tasks]
        for limit in (3, 6, 12):
            sample = sampler(specs, limit)
            surfaces = {spec.source["surface"] for spec in sample}
            self.assertEqual(
                len(surfaces),
                min(limit, 3),
                f"limit={limit} collapsed onto {surfaces}",
            )

    def test_both_drivers_share_one_sampler(self) -> None:
        """harness_eval and browser_batch must not resolve to different code.

        They carried independent copies once, and the copies diverged -- the
        browser proof kept the alphabetical sort after the harness driver was
        fixed, so its artifact reported a surface breakdown the sampler did
        not intend. Both now delegate to ``healthenv.sampling``.
        """
        harness_eval = _load_script("harness_eval.py")
        browser_batch = _load_script("browser_batch.py")
        for module in (harness_eval, browser_batch):
            self.assertIs(module._stratified_sample, stratified_sample)

    def test_shared_sampler_is_surface_fair_on_real_corpus(self) -> None:
        """The 1200-task corpus must spread 12 picks across all surfaces."""
        paths = sorted((Path(__file__).resolve().parents[1] / "generated" / "scale").glob("*.json"))
        if not paths:
            self.skipTest("compiled corpus not present")
        specs = [load_task(path) for path in paths]
        sample = stratified_sample(specs[:500], 12)
        counts = Counter(spec.source["surface"] for spec in sample)
        self.assertEqual(sum(counts.values()), 12)
        self.assertEqual(len(counts), 3, f"surfaces={dict(counts)}")
        self.assertEqual(min(counts.values()), 4, f"counts={dict(counts)}")


def _load_harness_eval() -> object:
    """Import ``scripts/harness_eval.py`` without adding scripts/ to the package tree."""
    return _load_script("harness_eval.py")


def _load_script(name: str) -> object:
    """Import a script from ``scripts/`` without adding it to the package tree."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"_{Path(name).stem}_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
