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
