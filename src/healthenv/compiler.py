"""Compile static longitudinal-health QA seeds into executable CUA task specs."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .llm import LLMError, OpenAICompatibleClient
from .schema import DEFAULT_SURFACE, SURFACES, QuestionSeed, TaskSpec

PLANNER_SYSTEM = (
    "You are a benchmark environment designer. Convert the supplied health QA seed into a concise "
    "computer-use workflow instruction. The agent must inspect a longitudinal record dashboard, "
    "select evidence, write a grounded care note, set a workflow priority, and submit. Return JSON "
    "with exactly two keys: instruction and rationale. Never reveal the supplied answer, expected "
    "evidence ids, or verifier. Do not diagnose, prescribe, or invent facts."
)


def _answer_terms(seed: QuestionSeed) -> list[str]:
    configured = seed.metadata.get("note_must_include")
    if isinstance(configured, list) and configured and all(isinstance(item, str) for item in configured):
        return configured
    answer = " ".join(seed.answer.split())
    numeric = re.findall(r"\b\d+(?:\.\d+)?\b", answer)
    units = re.findall(r"\b(?:mg/dl|mmhg|bpm|hours?|minutes?|steps?|kcal)\b", answer.casefold())
    terms = numeric[:2] + units[:1]
    if not terms and answer:
        terms = [answer[:80]]
    return terms


def _required_status(seed: QuestionSeed) -> str:
    status = seed.metadata.get("required_status", "review")
    if status not in {"routine", "review", "urgent"}:
        return "review"
    return str(status)


def _surface(seed: QuestionSeed) -> str:
    """Resolve the GUI surface, falling back safely on an unknown value.

    An unknown surface would leave the workbench unable to render the task, so
    the compiler never propagates one.
    """
    surface = seed.metadata.get("surface", DEFAULT_SURFACE)
    if surface not in SURFACES:
        return DEFAULT_SURFACE
    return str(surface)


def _default_instruction(seed: QuestionSeed) -> str:
    status = _required_status(seed)
    return (
        f"Review participant {seed.participant_id}'s timeline and answer this operational question: "
        f"{seed.question} Select every supporting record, document the conclusion in the care note, "
        f"set the case to {status.capitalize()}, and submit. Do not modify source records."
    )


def _llm_instruction(seed: QuestionSeed, client: OpenAICompatibleClient) -> tuple[str, str]:
    safe_seed = {
        "participant_id": seed.participant_id,
        "question": seed.question,
        "category": seed.category,
        "record_types": sorted({str(record.get("type")) for record in seed.records}),
        "record_count": len(seed.records),
    }
    result = client.complete_json(PLANNER_SYSTEM, json.dumps(safe_seed, ensure_ascii=False))
    instruction = str(result.get("instruction", "")).strip()
    rationale = str(result.get("rationale", "")).strip()
    if not instruction or len(instruction) > 1200:
        raise LLMError("planner returned an invalid instruction")
    if seed.answer and seed.answer.casefold() in instruction.casefold():
        raise LLMError("planner leaked the gold answer")
    required_phrases = ("select", "note", "submit")
    if not all(phrase in instruction.casefold() for phrase in required_phrases):
        raise LLMError("planner omitted required workflow operations")
    return instruction, rationale


def compile_seed(
    seed: QuestionSeed,
    *,
    llm_client: OpenAICompatibleClient | None = None,
    benchmark_name: str = "LifeAgentBench-style",
) -> TaskSpec:
    instruction = _default_instruction(seed)
    generation: dict[str, Any] = {
        "compiler": "healthenv",
        "mode": "deterministic",
        "llm_used_for_gold": False,
    }
    if llm_client is not None:
        try:
            instruction, rationale = _llm_instruction(seed, llm_client)
            generation.update(
                mode="llm-planned-deterministic-gold",
                model=llm_client.model,
                rationale=rationale,
            )
        except LLMError as error:
            generation.update(mode="deterministic-fallback", planner_error=str(error))

    digest = hashlib.sha256(f"{benchmark_name}:{seed.seed_id}".encode()).hexdigest()[:12]
    patient = {
        "id": seed.participant_id,
        "display_name": seed.metadata.get("display_name", f"Participant {seed.participant_id}"),
        "age_band": seed.metadata.get("age_band", "adult"),
    }
    verifier = {
        "required_evidence_ids": seed.evidence_ids,
        "allow_extra_evidence": False,
        "note_must_include": _answer_terms(seed),
            "required_status": _required_status(seed),
            "gold_source": "seed_answer_and_executable_evidence",
    }
    return TaskSpec(
        schema_version="0.1",
        task_id=f"healthenv-{digest}",
        source={
            "benchmark": benchmark_name,
            "seed_id": seed.seed_id,
            "category": seed.category,
            "question": seed.question,
            "surface": _surface(seed),
        },
        instruction=instruction,
        patient=patient,
        records=seed.records,
        initial_state={
            "selected_record_ids": [],
            "note": "",
            "status": "routine",
            "submitted": False,
            "forbidden_edits": [],
            "audit_log": [],
        },
        verifier=verifier,
        generation=generation,
    )


def compile_seed_file(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    llm_client: OpenAICompatibleClient | None = None,
    benchmark_name: str = "LifeAgentBench-style",
) -> list[Path]:
    source = Path(input_path)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            seed = QuestionSeed.from_dict(raw)
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"invalid seed at {source}:{line_number}: {error}") from error
        task = compile_seed(seed, llm_client=llm_client, benchmark_name=benchmark_name)
        output = destination / f"{task.task_id}.json"
        output.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        outputs.append(output)
    return outputs
