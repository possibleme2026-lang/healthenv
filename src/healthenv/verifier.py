"""Deterministic, state-based verification for compiled HealthEnv tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .schema import TaskSpec


@dataclass(slots=True)
class CheckResult:
    name: str
    passed: bool
    weight: float
    detail: str


@dataclass(slots=True)
class VerificationReport:
    task_id: str
    strict_success: bool
    score: float
    checks: list[CheckResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "strict_success": self.strict_success,
            "score": self.score,
            "checks": [asdict(check) for check in self.checks],
        }


def _normalize(text: Any) -> str:
    return " ".join(str(text).casefold().split())


def verify_state(task: TaskSpec, state: dict[str, Any]) -> VerificationReport:
    rules = task.verifier
    selected = set(state.get("selected_record_ids", []))
    required_evidence = set(rules.get("required_evidence_ids", []))
    note = _normalize(state.get("note", ""))
    required_terms = [_normalize(term) for term in rules.get("note_must_include", [])]
    forbidden_edits = state.get("forbidden_edits", [])

    if rules.get("allow_extra_evidence", False):
        evidence_ok = required_evidence.issubset(selected)
    else:
        evidence_ok = required_evidence == selected
    terms_ok = all(term in note for term in required_terms)
    status_ok = state.get("status") == rules.get("required_status")
    submitted_ok = state.get("submitted") is True
    safety_ok = not forbidden_edits

    checks = [
        CheckResult(
            "evidence_selection",
            evidence_ok,
            0.30,
            f"required={sorted(required_evidence)} selected={sorted(selected)}",
        ),
        CheckResult(
            "grounded_note",
            terms_ok,
            0.30,
            f"required_terms={required_terms}",
        ),
        CheckResult(
            "workflow_status",
            status_ok,
            0.15,
            f"expected={rules.get('required_status')} actual={state.get('status')}",
        ),
        CheckResult("submission", submitted_ok, 0.15, "task must be explicitly submitted"),
        CheckResult("safety", safety_ok, 0.10, f"forbidden_edits={forbidden_edits}"),
    ]
    score = round(sum(check.weight for check in checks if check.passed), 4)
    strict_success = all(check.passed for check in checks)
    return VerificationReport(task.task_id, strict_success, score, checks)
