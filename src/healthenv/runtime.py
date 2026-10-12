"""In-memory transactional state for a single benchmark task."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from .schema import DEFAULT_SURFACE, TaskSpec
from .verifier import verify_state


class ActionError(ValueError):
    pass


class TaskRuntime:
    def __init__(self, task: TaskSpec):
        self.task = task
        self._lock = RLock()
        self._initial_state = deepcopy(task.initial_state)
        self._state = deepcopy(task.initial_state)
        self._state.setdefault("selected_record_ids", [])
        self._state.setdefault("note", "")
        self._state.setdefault("status", "routine")
        self._state.setdefault("submitted", False)
        self._state.setdefault("forbidden_edits", [])
        self._state.setdefault("audit_log", [])

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def public_task(self) -> dict[str, Any]:
        """Return agent-visible task data without gold verifier values."""
        return {
            "schema_version": self.task.schema_version,
            "task_id": self.task.task_id,
            "instruction": self.task.instruction,
            "patient": self.task.patient,
            "records": self.task.records,
            "source": {
                "benchmark": self.task.source.get("benchmark"),
                "category": self.task.source.get("category"),
                # rendering metadata only: safe to expose, unlike question/gold
                "surface": self.task.source.get("surface") or DEFAULT_SURFACE,
            },
        }

    def agent_task(self) -> dict[str, Any]:
        """Strictly agent-visible view, behind an explicit information barrier.

        ``public_task`` is what the demonstration UI renders, so it still carries
        the benchmark category and the surface. An evaluated agent must not even
        see those, because the category names the reasoning skill and the surface
        correlates with it. This view therefore drops ``source`` entirely and
        exposes only what a real operator would have: the instruction, the
        participant header, and the raw records.
        """
        return {
            "schema_version": self.task.schema_version,
            "task_id": self.task.task_id,
            "instruction": self.task.instruction,
            "patient": self.task.patient,
            "records": self.task.records,
        }

    def agent_submission(self) -> dict[str, Any]:
        """Submit acknowledgement with no verifier signal at all.

        Episodes are scored offline. Returning check-level detail here would hand
        the agent a gold oracle it could hill-climb against (``detail`` on the
        evidence check spells out the required record ids), so the agent-facing
        path deliberately returns none of it.
        """
        return {"ok": True, "submitted": self._state.get("submitted") is True}

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._state = deepcopy(self._initial_state)
            self._state.update(
                selected_record_ids=[],
                note="",
                status="routine",
                submitted=False,
                forbidden_edits=[],
                audit_log=[],
            )
            return self.snapshot()

    def apply(self, action: dict[str, Any]) -> dict[str, Any]:
        name = action.get("type")
        with self._lock:
            if self._state.get("submitted") and name != "reset":
                raise ActionError("task is already submitted; reset before editing")
            if name == "select_record":
                self._select_record(str(action.get("record_id", "")), bool(action.get("selected", True)))
            elif name == "set_note":
                note = str(action.get("note", "")).strip()
                if len(note) > 2000:
                    raise ActionError("note exceeds 2000 characters")
                self._state["note"] = note
            elif name == "set_status":
                status = action.get("status")
                if status not in {"routine", "review", "urgent"}:
                    raise ActionError("invalid status")
                self._state["status"] = status
            elif name == "submit":
                self._state["submitted"] = True
            elif name == "reset":
                return self.reset()
            else:
                raise ActionError(f"unsupported action: {name!r}")
            self._state["audit_log"].append(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "type": name,
                    "payload": {key: value for key, value in action.items() if key != "note"},
                }
            )
            return self.snapshot()

    def _select_record(self, record_id: str, selected: bool) -> None:
        valid_ids = {str(record.get("id")) for record in self.task.records}
        if record_id not in valid_ids:
            raise ActionError(f"unknown record: {record_id}")
        current = set(self._state.get("selected_record_ids", []))
        if selected:
            current.add(record_id)
        else:
            current.discard(record_id)
        self._state["selected_record_ids"] = sorted(current)

    def verification(self) -> dict[str, Any]:
        with self._lock:
            return verify_state(self.task, self._state).to_dict()
