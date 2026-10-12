# HealthEnv Task IR v0.1

A task is a JSON object that separates agent-visible state from hidden verification state.

## Top-level fields

| Field | Visibility | Purpose |
|---|---|---|
| `schema_version` | public | Contract version; currently `0.1`. |
| `task_id` | public | Stable hash of benchmark and source seed id. |
| `source` | partial | Benchmark/category are public; question and seed provenance remain in the task artifact. `source.surface` names the presentation skin. |
| `instruction` | public | Operational workflow shown to the agent. |
| `patient` | public | Synthetic participant metadata. |
| `records` | public | Read-only longitudinal observations. |
| `initial_state` | runtime | Empty evidence selection, note, status, audit log, and submission flag. |
| `verifier` | hidden | Required evidence, grounded note terms, expected workflow status, and gold provenance. |
| `generation` | audit | Compiler mode, optional planner model, fallback reason, and gold-generation boundary. |

## Interface surfaces

`source.surface` is one of `timeline`, `vitals-dashboard`, or `clinical-ledger`. It is assigned at seed time (400/400/400 across the corpus, orthogonal to the reasoning skill) and controls **presentation only**: the record set, the gold evidence, the note terms, and the verifier weights are identical across surfaces. The demo browser renders each surface with a distinct layout; the sealed agent channel strips the field entirely so an evaluated agent cannot condition on it.

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

## Agent channel

The evaluated agent never sees the demo channel. `healthenv.agentenv` serves a tool API instead:

| Endpoint | Method | Purpose |
|---|---|---|
| `/manifest` | GET | Tool list with argument schemas and the step budget. |
| `/tool` | GET | Execute one tool call from query parameters. |
| `/tool` | POST | Equivalent alias with a JSON body. |

Tools: `get_task`, `list_records`, `read_state`, `select_record`, `set_note`, `set_status`, `submit`. The task projection strips `source` (including `category` and `surface`) and every verifier field. `submit` returns `{"ok": true, "submitted": true}` and no verification payload; scoring happens offline after the episode. `/api/verify`, `/api/task`, and `/api/state` are 404 on this server.

The GET transport is the documented one because a quoted JSON body is corrupted by PowerShell 5.1 (`{tool:get_task,...}`), which two of the three evaluated harnesses drive as their shell; the query form is byte-identical under bash and PowerShell. A regression test asserts the two transports return identical results.

The current schema is intentionally narrow. A production research release should add typed temporal predicates, cross-application state, document artifacts, role-based permissions, and executable clinical safety invariants.
