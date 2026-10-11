"""Typed, dependency-free schemas for QA seeds and compiled CUA tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class SchemaError(ValueError):
    """Raised when a seed or task violates the public HealthEnv schema."""


def _require(mapping: dict[str, Any], key: str, expected: type) -> Any:
    value = mapping.get(key)
    if not isinstance(value, expected):
        raise SchemaError(f"{key!r} must be {expected.__name__}")
    return value


@dataclass(slots=True)
class QuestionSeed:
    seed_id: str
    participant_id: str
    question: str
    answer: str
    category: str
    records: list[dict[str, Any]]
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> QuestionSeed:
        records = _require(raw, "records", list)
        seen: set[str] = set()
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise SchemaError(f"records[{index}] must be an object")
            record_id = _require(record, "id", str)
            if record_id in seen:
                raise SchemaError(f"duplicate record id: {record_id}")
            seen.add(record_id)
            _require(record, "date", str)
            _require(record, "type", str)
            if "value" not in record:
                raise SchemaError(f"records[{index}].value is required")
        evidence_ids = raw.get("evidence_ids", [])
        if not isinstance(evidence_ids, list) or not all(isinstance(item, str) for item in evidence_ids):
            raise SchemaError("evidence_ids must be a string list")
        unknown = sorted(set(evidence_ids) - seen)
        if unknown:
            raise SchemaError(f"evidence_ids not found in records: {unknown}")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            raise SchemaError("metadata must be an object")
        return cls(
            seed_id=_require(raw, "seed_id", str),
            participant_id=_require(raw, "participant_id", str),
            question=_require(raw, "question", str),
            answer=str(raw.get("answer", "")),
            category=_require(raw, "category", str),
            records=records,
            evidence_ids=evidence_ids,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TaskSpec:
    schema_version: str
    task_id: str
    source: dict[str, Any]
    instruction: str
    patient: dict[str, Any]
    records: list[dict[str, Any]]
    initial_state: dict[str, Any]
    verifier: dict[str, Any]
    generation: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TaskSpec:
        if raw.get("schema_version") != "0.1":
            raise SchemaError("schema_version must be '0.1'")
        records = _require(raw, "records", list)
        initial_state = _require(raw, "initial_state", dict)
        verifier = _require(raw, "verifier", dict)
        if verifier.get("required_status") not in {"routine", "review", "urgent"}:
            raise SchemaError("verifier.required_status must be routine, review, or urgent")
        return cls(
            schema_version="0.1",
            task_id=_require(raw, "task_id", str),
            source=_require(raw, "source", dict),
            instruction=_require(raw, "instruction", str),
            patient=_require(raw, "patient", dict),
            records=records,
            initial_state=initial_state,
            verifier=verifier,
            generation=_require(raw, "generation", dict),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
