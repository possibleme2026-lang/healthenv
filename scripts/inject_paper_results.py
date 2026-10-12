"""Inject the cross-harness results into the paper, straight from the artifact.

No number in the paper's results section is typed by hand: this script reads
artifacts/harness_eval.json and rewrites the placeholder blocks in
paper/healthenv.md. If the artifact is missing, the script exits non-zero so a
stale placeholder can never survive into a release.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "harness_eval.json"
PAPER = ROOT / "paper" / "healthenv.md"

TABLE_PLACEHOLDER = "RESULTS_TABLE_PLACEHOLDER"
PROSE_PLACEHOLDER = "RESULTS_PROSE_PLACEHOLDER"
FAILURE_PLACEHOLDER = "FAILURE_MODES_PLACEHOLDER"


def _fmt_seconds(seconds: float) -> str:
    return f"{seconds:.0f}s" if seconds < 90 else f"{seconds / 60:.1f}min"


def build_table(summary: dict) -> str:
    harnesses = summary["harnesses"]
    order = [name for name in ("pi", "codex", "deepseek") if name in harnesses]
    header = (
        "| Harness | Episodes | Strict success | Mean score | Submissions | "
        "Timeouts | Mean steps | Mean elapsed |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|\n"
    )
    rows = []
    for name in order:
        h = harnesses[name]
        rows.append(
            f"| {h['display_name']} (`{name}`) | {h['episodes']} "
            f"| {h['strict_successes']}/{h['episodes']} ({h['strict_success_rate']:.0%}) "
            f"| {h['mean_score']:.2f} "
            f"| {h['submissions']} "
            f"| {h['timeouts']} "
            f"| {h['mean_steps']:.1f} "
            f"| {_fmt_seconds(h['mean_elapsed_seconds'])} |"
        )
    return header + "\n".join(rows)


def build_prose(summary: dict) -> str:
    harnesses = summary["harnesses"]
    order = [name for name in ("pi", "codex", "deepseek") if name in harnesses]
    parts: list[str] = []
    rates = {name: harnesses[name]["strict_success_rate"] for name in order}
    best = max(rates, key=lambda name: rates[name])
    worst = min(rates, key=lambda name: rates[name])
    parts.append(
        f"Across {len(order)} harnesses and "
        f"{harnesses[order[0]]['episodes']} episodes each, strict success ranges from "
        f"{rates[worst]:.0%} ({harnesses[worst]['display_name']}) to "
        f"{rates[best]:.0%} ({harnesses[best]['display_name']}) — the same model, "
        "the same tasks, and the same prompt bytes on every run."
    )
    # surface breakdown highlights
    for name in order:
        by_surface = harnesses[name]["by_surface"]
        if len(by_surface) < 2:
            continue
        spread = {
            surface: bucket["success_rate"] for surface, bucket in by_surface.items()
        }
        parts.append(
            f"On {harnesses[name]['display_name']}, strict success by rendered surface is "
            + ", ".join(f"{surface} {rate:.0%}" for surface, rate in sorted(spread.items()))
            + "."
        )
    return "\n\n".join(parts)


def build_failures(summary: dict) -> str:
    harnesses = summary["harnesses"]
    order = [name for name in ("pi", "codex", "deepseek") if name in harnesses]
    lines: list[str] = []
    all_checks: set[str] = set()
    for name in order:
        all_checks.update(harnesses[name]["failed_checks"])
    if not all_checks:
        return "No verifier checks failed in this run."
    header = "| Failed check | " + " | ".join(harnesses[n]["display_name"] for n in order) + " |\n"
    header += "|---" * (len(order) + 1) + "|\n"
    for check in sorted(all_checks):
        cells = []
        for name in order:
            h = harnesses[name]
            count = h["failed_checks"].get(check, 0)
            cells.append(f"{count}/{h['episodes']}")
        lines.append(f"| {check.replace('_', ' ')} | " + " | ".join(cells) + " |")
    body = header + "\n".join(lines)
    return body + "\n\n" + _failure_note(summary)


def _failure_note(summary: dict) -> str:
    """Describe the observed score distribution, not a hypothesised one."""
    records = summary.get("records", [])
    if not records:
        return (
            "Episode-level scores are not recorded in this artifact, so the "
            "distribution of partial credit cannot be reported from it."
        )
    counts: dict[float, int] = {}
    for record in records:
        score = round(float(record.get("score", 0.0)), 2)
        counts[score] = counts.get(score, 0) + 1
    spread = ", ".join(f"{count} at {score:.2f}" for score, count in sorted(counts.items()))
    lowest = min(counts)
    if lowest > 0.10:
        parts = [
            f"Episode scores across all {len(records)} runs were {spread} — no episode "
            "in this run scored the 0.10 safety floor at which only the safety check "
            "passes, so every harness could start, act, and submit."
        ]
    else:
        parts = [f"Episode scores across all {len(records)} runs were {spread}."]
    # Which reasoning skill the residual failures concentrate in.
    by_category: dict[str, list[int]] = {}
    for record in records:
        bucket = by_category.setdefault(str(record.get("category", "unknown")), [0, 0])
        bucket[1] += 1
        if record.get("strict_success"):
            bucket[0] += 1
    unsolved = [name for name, (ok, total) in by_category.items() if ok == 0 and total]
    solved = [name for name, (ok, total) in by_category.items() if total and ok == total]
    if unsolved:
        parts.append(
            "No harness solved a "
            + ", ".join(sorted(unsolved))
            + " task, while every harness solved "
            + (", ".join(sorted(solved)) if solved else "none of the other skills")
            + " — the residual failures concentrate in a reasoning skill rather "
            "than in a harness."
        )
    return " ".join(parts)


def main() -> int:
    if not ARTIFACT.is_file():
        raise SystemExit(f"missing artifact: {ARTIFACT}; run scripts/harness_eval.py first")
    summary = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    paper = PAPER.read_text(encoding="utf-8")
    missing = [
        marker
        for marker in (TABLE_PLACEHOLDER, PROSE_PLACEHOLDER, FAILURE_PLACEHOLDER)
        if marker not in paper
    ]
    if missing:
        raise SystemExit(f"paper no longer contains placeholders: {missing}")
    paper = paper.replace(TABLE_PLACEHOLDER, build_table(summary))
    paper = paper.replace(PROSE_PLACEHOLDER, build_prose(summary))
    paper = paper.replace(FAILURE_PLACEHOLDER, build_failures(summary))
    PAPER.write_text(paper, encoding="utf-8")
    print(f"injected results into {PAPER}")
    for harness in summary["harnesses"].values():
        print(f"  {harness['display_name']}: {harness['strict_successes']}/{harness['episodes']} strict")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
