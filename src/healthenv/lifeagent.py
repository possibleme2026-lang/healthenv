"""Adapter for the public LifeAgentBench JSONL question format.

The upstream repository currently has no detected license, so this adapter reads a
user-provided local checkout and does not redistribute upstream data. It builds a
new synthetic record state that preserves the executable relation in a QA item.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .schema import QuestionSeed, SchemaError

_PARTICIPANT = re.compile(r"\bA4F_\d+\b")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _clean_query(query: str) -> str:
    text = re.sub(r"\nOutput requirement:.*$", "", query, flags=re.DOTALL).strip()
    text = re.sub(r"\{([^}]+)\}", lambda match: match.group(1).replace("_", " "), text)
    return " ".join(text.split())


def _comparison_seed(query: str, answer: str, source_id: str) -> QuestionSeed:
    participant_match = _PARTICIPANT.search(query)
    dates = _DATE.findall(query)
    answer_match = _NUMBER.search(answer)
    if not participant_match or not dates or not answer_match:
        raise SchemaError("item is not a supported dated numeric comparison")
    participant = participant_match.group(0)
    current_date = dates[-1]
    delta = float(answer_match.group(0))
    digest = int(hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:6], 16)
    baseline = 94 + digest % 3
    current = baseline + delta
    metric = "oxygen saturation" if "oxygen" in query.casefold() else "health metric"
    previous_date = "previous day"
    unit = "%" if metric == "oxygen saturation" else "units"
    records = [
        {
            "id": "evidence-previous",
            "date": previous_date,
            "type": metric,
            "value": baseline,
            "unit": unit,
            "detail": "Synthetic previous-period upper bound generated from the QA relation.",
        },
        {
            "id": "evidence-current",
            "date": current_date,
            "type": metric,
            "value": current,
            "unit": unit,
            "detail": "Synthetic current-period upper bound generated from the QA relation.",
        },
        {
            "id": "distractor-awake",
            "date": current_date,
            "type": metric,
            "value": max(90, current - 3),
            "unit": unit,
            "detail": "Awake-period summary; not evidence for the sleeping comparison.",
        },
    ]
    delta_text = f"{delta:g}"
    return QuestionSeed(
        seed_id=f"lifeagent-{source_id}",
        participant_id=participant,
        question=_clean_query(query),
        answer=delta_text,
        category="longitudinal-comparison",
        records=records,
        evidence_ids=["evidence-previous", "evidence-current"],
        metadata={
            "display_name": f"Participant {participant}",
            "required_status": "review",
            "note_must_include": [delta_text, "percentage points" if unit == "%" else unit],
            "upstream_payload_redistributed": False,
            "synthetic_record_state": True,
        },
    )


def import_lifeagent_item(path: str | Path, line_number: int = 1) -> QuestionSeed:
    source = Path(path)
    if line_number < 1:
        raise ValueError("line_number must be >= 1")
    selected: str | None = None
    with source.open("r", encoding="utf-8") as handle:
        for current, line in enumerate(handle, 1):
            if current == line_number:
                selected = line
                break
    if selected is None:
        raise ValueError(f"line {line_number} not found in {source}")
    raw: dict[str, Any] = json.loads(selected)
    query = raw.get("Query")
    answer = raw.get("Answer")
    if not isinstance(query, str) or not isinstance(answer, (str, int, float)):
        raise SchemaError("LifeAgentBench item must contain Query and Answer")
    source_hash = hashlib.sha256(selected.encode("utf-8")).hexdigest()[:12]
    return _comparison_seed(query, str(answer), source_hash)
