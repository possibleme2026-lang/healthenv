# Changelog

All notable changes are documented here.

## 0.1.0 - 2026-10-11

- Added the QA-to-CUA compiler, task IR, browser runtime, and deterministic verifier.
- Added synthetic longitudinal health tasks and a local LifeAgentBench-format adapter.
- Added optional TierFlow/OpenAI-compatible instruction planning with deterministic gold isolation.
- Added bilingual documentation, technical report draft, and reproducibility artifacts.
- Added a browser-free CLI evaluation path (`healthenv oracle` + `healthenv verify`).

## 0.2.0 - 2026-10-12

- Added `healthenv.seedgen`: deterministic synthesis of QA seeds across 10 metric
  domains and 7 reasoning skills, with answers derived from the generated records.
- Added `scripts/scale_eval.py` and a checked-in run of **1200 environments**, each
  proved individually (oracle strict success plus four negative controls: no
  evidence, every record selected, ungrounded note, wrong workflow priority).
- Added `healthenv generate-seeds` and a `scale` CI job with `--check`, which
  requires the regenerated report to match the committed one.
- Verifier note terms now match on word boundaries, so a note that only says
  `2024` no longer satisfies a required term of `2`.
- Instructions now state the required workflow priority instead of always
  saying `Review`; priorities vary across routine/review/urgent.

## 0.3.0 - 2026-10-12

- Added the **three-surface browser workbench**: every compiled task renders as
  `timeline`, `vitals-dashboard`, or `clinical-ledger` (400/400/400, orthogonal
  to the reasoning skill). Surfaces change presentation only — never the
  evidence, the gold answer, or the verifier.
- Added `healthenv.agentenv`: a sealed agent-facing tool server (`/manifest`,
  `/tool`) with a trajectory recorder and step budget. `/api/verify` is not
  reachable through it, and `submit` returns no verification payload.
- Added `healthenv.harness` + `scripts/harness_eval.py`: cross-harness
  evaluation of `pi`, Codex CLI, and DeepSeek `dsh` under one model, one prompt,
  one tool surface, and offline scoring. The stratified sampler is surface-first
  (the original flat round-robin collapsed onto `clinical-ledger` for small
  limits, which is fixed and regression-tested).
- Tool API gains a **GET transport with query parameters**. Measured: a quoted
  JSON POST body is corrupted by PowerShell 5.1 (`{tool:get_task,...}`), which
  `codex` and `dsh` drive; the query form is byte-identical under bash and
  PowerShell. POST is kept as an equivalent alias and a test asserts equivalence.
- Documented interface hazards with the probes that exposed them: multi-line
  argv prompts truncated to the first line (codex; fixed by stdin transport),
  transcript markers matched against the prompt echo (fixed by reading
  submission state from the episode), pi's shell discovery limited to Program
  Files (fixed by a per-run `shellPath`), and dsh's Windows ACL sandbox failing
  closed (fixed by matching codex's full-access mode).
- Paper extended with the cross-harness evaluation (§5), the surface design
  (§3.6), and the sealed agent channel (§3.7); figures 3–4 render from
  `artifacts/harness_eval.json`.
- Measured cross-harness results (12 tasks each, one model `tierflow_pro`):
  pi 6/12 strict, Codex CLI 7/12, DeepSeek `dsh` 5/12. Every episode
  submitted and no episode hit the 0.10 safety floor; the dominant miss is
  evidence selection. Injected into the paper by
  `scripts/inject_paper_results.py`, so no §5 number is typed by hand.
- Extracted the stratified sampler into `healthenv.sampling`.
  `scripts/browser_batch.py` carried an independent copy with the same
  alphabetical-collapse defect as the one fixed in `harness_eval.py` (its smoke
  artifact recorded 6/6 `clinical-ledger` for `--limit 6`); both drivers now
  alias one implementation and a test asserts they are the same object.
- `scripts/browser_batch.py` now runs the corpus in **chunks** (servers boot
  per chunk and the browser persists across chunks), so the full 1200-task
  browser proof is feasible on a laptop. The driver's wait conditions report
  the observed UI state on timeout instead of a bare "timed out".
