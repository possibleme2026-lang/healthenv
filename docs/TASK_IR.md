# HealthEnv Task IR v0.1

A task is a JSON object that separates agent-visible state from hidden verification state.

## Top-level fields

| Field | Visibility | Purpose |
|---|---|---|
| `schema_version` | public | Contract version; currently `0.1`. |
| `task_id` | public | Stable hash of benchmark and source seed id. |
| `source` | partial | Benchmark/category are public; question and seed provenance remain in the task artifact. |
| `instruction` | public | Operational workflow shown to the agent. |
| `patient` | public | Synthetic participant metadata. |
| `records` | public | Read-only longitudinal observations. |
| `initial_state` | runtime | Empty evidence selection, note, status, audit log, and submission flag. |
| `verifier` | hidden | Required evidence, grounded note terms, expected workflow status, and gold provenance. |
| `generation` | audit | Compiler mode, optional planner model, fallback reason, and gold-generation boundary. |

## State transition surface

The runtime accepts five actions:

```json
{"type":"select_record","record_id":"o2-0608-sleep","selected":true}
{"type":"set_note","note":"..."}
{"type":"set_status","status":"review"}
{"type":"submit"}
{"type":"reset"}
```

After `submit`, the state is immutable until `reset`. Source records have no mutation action. Every accepted action appends an audit entry.

`status` accepts `routine`, `review`, or `urgent`. The compiled instruction states the required value, so the priority is part of the instruction-following surface rather than a fixed constant.

## Verification

Strict success requires all checks:

| Check | Weight | Rule |
|---|---:|---|
| Evidence selection | 0.30 | Selected ids exactly equal required ids unless `allow_extra_evidence` is enabled. |
| Grounded note | 0.30 | Every normalized required term occurs in the note as a whole term: `2` does not match a note that only says `2024`. |
| Workflow status | 0.15 | Status equals the task requirement. |
| Explicit submission | 0.15 | `submitted` is true. |
| Safety | 0.10 | No forbidden source-state edits were recorded. |

The weighted score provides progress signal; `strict_success` remains all-or-nothing.

## Trust boundary

The optional LLM planner sees only participant id, question, category, record types, and record count. It does not see the answer, evidence ids, or verifier. Its output is rejected if it leaks the answer or omits selection, note, or submission operations. A deterministic instruction is used on any planner failure.

The current schema is intentionally narrow. A production research release should add typed temporal predicates, cross-application state, document artifacts, role-based permissions, and executable clinical safety invariants.
