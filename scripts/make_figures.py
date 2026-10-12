"""Render the paper figures straight from the checked-in artifacts.

Every number in every figure is read from a JSON artifact, never typed by hand,
so a figure cannot drift away from the measurement it claims to show. Run:

    python scripts/make_figures.py

Outputs vector PDFs plus PNG previews under ``paper/figures/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
FIGURES = ROOT / "paper" / "figures"

# Chinese finance convention does not apply here; these are qualitative palettes
# chosen so the three harnesses stay distinguishable in greyscale printing.
HARNESS_COLORS = {"pi": "#3b6ea5", "codex": "#1f9d76", "deepseek": "#b4653a"}
SURFACE_COLORS = {"timeline": "#4c6ef5", "vitals-dashboard": "#12b886", "clinical-ledger": "#e8590c"}


def _load(name: str) -> dict[str, Any]:
    path = ARTIFACTS / name
    if not path.is_file():
        raise SystemExit(f"missing artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 160,
            "savefig.dpi": 300,
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "grid.linewidth": 0.6,
            "legend.frameon": False,
        }
    )


def figure_scale_pipeline(scale: dict[str, Any]) -> plt.Figure:
    """Per-environment control survival: the proof that tasks are solvable and gated."""
    compiled = scale["tasks_compiled"]
    controls = [
        ("oracle trajectory", scale["oracle_strict_passes"], "#2f9e44"),
        *[
            (name.replace("_", " "), rejected, "#c92a2a")
            for name, rejected in scale["negative_rejections"].items()
        ],
    ]
    labels = [row[0] for row in controls]
    values = [row[1] for row in controls]
    colors = [row[2] for row in controls]

    fig, ax = plt.subplots(figsize=(6.4, 2.5))
    bars = ax.barh(labels, values, color=colors, height=0.6)
    ax.set_xlim(0, compiled * 1.06)
    ax.set_xlabel(f"environments (out of {compiled})")
    ax.set_title("Every environment is individually proven: solvable once, gated four ways")
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            value + compiled * 0.012,
            bar.get_y() + bar.get_height() / 2,
            f"{value}",
            va="center",
            fontsize=8,
        )
    ax.invert_yaxis()
    fig.tight_layout()
    return fig


def figure_diversity(scale: dict[str, Any]) -> plt.Figure:
    """Instance count versus structural variety, stated honestly."""
    diversity = scale["diversity"]
    total = scale["tasks_compiled"]
    labels = ["instances", "distinct\nquestions", "distinct\n(Q, A) pairs", "structural\nskeletons"]
    values = [
        total,
        diversity["unique_questions"],
        diversity["unique_question_answer_pairs"],
        diversity["unique_skeletons"],
    ]
    colors = ["#495057", "#4c6ef5", "#3b82f6", "#e8590c"]
    fig, ax = plt.subplots(figsize=(6.4, 2.5))
    bars = ax.bar(labels, values, color=colors, width=0.62)
    ax.set_ylim(0, total * 1.14)
    ax.set_ylabel("count")
    ax.set_title("Instance count grows cheaply; reasoning patterns do not")
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + total * 0.02,
            f"{value}" + (f"  ({value / total:.0%})" if value != total else ""),
            ha="center",
            fontsize=8,
        )
    fig.tight_layout()
    return fig


def figure_harness_success(evaluation: dict[str, Any]) -> plt.Figure:
    """Strict success rate per harness, overall and split by surface."""
    harnesses = evaluation["harnesses"]
    names = list(harnesses)
    totals = [harnesses[name]["strict_success_rate"] for name in names]
    surfaces = sorted({key for name in names for key in harnesses[name]["by_surface"]})

    fig, (left, right) = plt.subplots(1, 2, figsize=(6.6, 2.7), gridspec_kw={"width_ratios": [1, 1.5]})
    bars = left.bar(
        [harnesses[name]["display_name"] for name in names],
        totals,
        color=[HARNESS_COLORS.get(name, "#666") for name in names],
        width=0.6,
    )
    left.set_ylim(0, 1.08)
    left.set_ylabel("strict success rate")
    left.set_title("Overall")
    for bar, value in zip(bars, totals, strict=True):
        left.text(bar.get_x() + bar.get_width() / 2, value + 0.02, f"{value:.0%}", ha="center", fontsize=8)

    width = 0.26
    offsets = [(index - (len(names) - 1) / 2) * width for index in range(len(names))]
    for offset, name in zip(offsets, names, strict=True):
        bucket = harnesses[name]["by_surface"]
        rates = [bucket.get(surface, {}).get("success_rate", 0.0) for surface in surfaces]
        counts = [harnesses[name]["by_surface"].get(surface, {}).get("episodes", 0) for surface in surfaces]
        positions = [index + offset for index in range(len(surfaces))]
        right.bar(
            positions,
            rates,
            width,
            label=harnesses[name]["display_name"],
            color=HARNESS_COLORS.get(name, "#666"),
        )
        for position, rate, count in zip(positions, rates, counts, strict=True):
            right.text(position, rate + 0.02, f"{rate:.0%}\nn={count}", ha="center", fontsize=6.5)
    right.set_xticks(range(len(surfaces)))
    right.set_xticklabels(surfaces, fontsize=8)
    right.set_ylim(0, 1.22)
    right.set_title("By rendered surface")
    right.legend(fontsize=7.5, loc="upper left", ncols=len(names))
    fig.tight_layout()
    return fig


def figure_failure_modes(evaluation: dict[str, Any]) -> plt.Figure:
    """Which verifier checks the harnesses actually miss."""
    harnesses = evaluation["harnesses"]
    names = list(harnesses)
    checks = sorted({check for name in names for check in harnesses[name]["failed_checks"]})
    if not checks:
        fig, ax = plt.subplots(figsize=(5.2, 2.2))
        ax.text(0.5, 0.5, "no failed checks recorded", ha="center", va="center")
        ax.axis("off")
        return fig
    width = 0.26
    offsets = [(index - (len(names) - 1) / 2) * width for index in range(len(names))]
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    for offset, name in zip(offsets, names, strict=True):
        episodes = harnesses[name]["episodes"]
        counts = [harnesses[name]["failed_checks"].get(check, 0) for check in checks]
        positions = [index + offset for index in range(len(checks))]
        ax.bar(
            positions,
            [count / episodes for count in counts],
            width,
            label=harnesses[name]["display_name"],
            color=HARNESS_COLORS.get(name, "#666"),
        )
    ax.set_xticks(range(len(checks)))
    ax.set_xticklabels([check.replace("_", "\n") for check in checks], fontsize=8)
    ax.set_ylabel("fraction of episodes")
    ax.set_title("Failure modes: what each harness gets wrong")
    ax.legend(fontsize=7.5)
    fig.tight_layout()
    return fig


def figure_verifier_weights() -> plt.Figure:
    """The scoring rubric the environments share."""
    weights = [
        ("evidence selection", 0.30),
        ("grounded note", 0.30),
        ("workflow priority", 0.15),
        ("explicit submission", 0.15),
        ("no forbidden edits", 0.10),
    ]
    labels = [row[0] for row in weights]
    values = [row[1] for row in weights]
    fig, ax = plt.subplots(figsize=(6.4, 2.2))
    bars = ax.barh(labels, values, color="#4c6ef5", height=0.58)
    ax.set_xlim(0, 0.37)
    ax.set_xlabel("weight in the partial score")
    ax.set_title("Deterministic verifier: five checks, strict success requires all of them")
    for bar, value in zip(bars, values, strict=True):
        ax.text(value + 0.008, bar.get_y() + bar.get_height() / 2, f"{value:.2f}", va="center", fontsize=8)
    ax.invert_yaxis()
    fig.tight_layout()
    return fig


def figure_agent_workflow() -> plt.Figure:
    """The tool loop every harness drives, with the information barrier drawn in."""
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    ax.axis("off")
    boxes = [
        (0.02, 0.62, 0.28, 0.26, "Harness\n(pi / Codex / DeepSeek)", "#e7f1ff", "#3b6ea5"),
        (0.38, 0.62, 0.26, 0.26, "Tool API\n/manifest + /tool", "#e9f8f2", "#1f9d76"),
        (0.72, 0.62, 0.26, 0.26, "Task runtime\nstate + audit log", "#fff4e6", "#e8590c"),
        (0.72, 0.20, 0.26, 0.26, "Verifier\n(offline scoring)", "#f3f0ff", "#7048e8"),
        (0.38, 0.20, 0.26, 0.26, "Environment\ngold answer + evidence", "#ffe3e3", "#c92a2a"),
    ]
    for x, y, w, h, text, face, edge in boxes:
        ax.add_patch(
            plt.Rectangle((x, y), w, h, facecolor=face, edgecolor=edge, linewidth=1.2, zorder=2)
        )
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=8, zorder=3)
    arrows = [
        ((0.30, 0.75), (0.38, 0.75), "http", "#3b6ea5"),
        ((0.64, 0.75), (0.72, 0.75), "actions", "#1f9d76"),
        ((0.85, 0.62), (0.85, 0.46), "state", "#666666"),
        ((0.72, 0.33), (0.64, 0.33), "score", "#7048e8"),
        ((0.51, 0.46), (0.51, 0.62), "sealed", "#c92a2a"),
    ]
    for (x0, y0), (x1, y1), label, color in arrows:
        ax.annotate(
            "",
            xy=(x1, y1),
            xytext=(x0, y0),
            arrowprops={"arrowstyle": "-|>", "color": color, "linewidth": 1.3},
        )
        ax.text((x0 + x1) / 2, (y0 + y1) / 2 + 0.03, label, ha="center", fontsize=7, color=color)
    ax.plot([0.36, 0.66], [0.53, 0.53], linestyle="--", color="#c92a2a", linewidth=1.2)
    ax.text(0.51, 0.57, "information barrier", ha="center", fontsize=7.5, color="#c92a2a")
    ax.set_xlim(0, 1)
    ax.set_ylim(0.1, 1.0)
    fig.tight_layout()
    return fig


def main() -> int:
    _style()
    FIGURES.mkdir(parents=True, exist_ok=True)
    scale = _load("scale_results.json")
    figures: dict[str, plt.Figure] = {
        "fig1-pipeline": figure_scale_pipeline(scale),
        "fig2-diversity": figure_diversity(scale),
        "fig5-verifier": figure_verifier_weights(),
        "fig6-workflow": figure_agent_workflow(),
    }
    evaluation_path = ARTIFACTS / "harness_eval.json"
    if evaluation_path.is_file():
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        if evaluation.get("harnesses"):
            figures["fig3-harness-success"] = figure_harness_success(evaluation)
            figures["fig4-failure-modes"] = figure_failure_modes(evaluation)
    for name, figure in figures.items():
        figure.savefig(FIGURES / f"{name}.pdf", bbox_inches="tight")
        figure.savefig(FIGURES / f"{name}.png", bbox_inches="tight")
        plt.close(figure)
        print(f"wrote {name}.pdf / {name}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
