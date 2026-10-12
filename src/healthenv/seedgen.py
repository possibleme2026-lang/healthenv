"""Deterministic synthesis of longitudinal-health QA seeds at benchmark scale.

The generator is combinatorial rather than templated: every seed combines a
metric domain, a reasoning skill, a date window, a distractor plan, and a
workflow priority. Answers are always *derived from the generated records*, so
the compiled verifier checks a conclusion the records actually support.

Nothing here copies an upstream benchmark payload. Every record is synthetic.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .schema import SURFACES, QuestionSeed

SEEDGEN_VERSION = "healthenv.seedgen/0.1"


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """A synthetic physiological domain with a clinically plausible range."""

    key: str
    label: str
    unit: str
    delta_unit: str
    low: float
    high: float
    decimals: int
    higher_is_worse: bool = False


METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("oxygen_saturation", "oxygen saturation", "%", "percentage points", 88.0, 100.0, 0),
    MetricSpec("sleep_duration", "sleep duration", "hours", "hours", 3.0, 10.0, 1),
    MetricSpec("resting_heart_rate", "resting heart rate", "bpm", "bpm", 46.0, 98.0, 0, True),
    MetricSpec("blood_glucose", "blood glucose", "mg/dL", "mg/dL", 70.0, 190.0, 0, True),
    MetricSpec("systolic_bp", "systolic blood pressure", "mmHg", "mmHg", 95.0, 168.0, 0, True),
    MetricSpec("step_count", "step count", "steps", "steps", 1500.0, 18000.0, 0),
    MetricSpec("body_weight", "body weight", "kg", "kg", 48.0, 112.0, 1),
    MetricSpec("active_minutes", "active minutes", "minutes", "minutes", 5.0, 130.0, 0),
    MetricSpec("stress_score", "stress score", "score", "points", 8.0, 92.0, 0, True),
    MetricSpec("hydration_intake", "hydration intake", "ml", "ml", 800.0, 3500.0, 0),
)

COUNTABLE_METRICS = frozenset({"step_count", "active_minutes", "hydration_intake"})


def _round_value(value: float, decimals: int) -> float:
    if decimals == 0:
        return float(round(value))
    return round(value, decimals)


def _fmt(value: float, decimals: int) -> str:
    if decimals == 0:
        return str(int(round(value)))
    return f"{value:.{decimals}f}"


def _sample(rng: random.Random, metric: MetricSpec) -> float:
    return _round_value(rng.uniform(metric.low, metric.high), metric.decimals)


def _sample_between(rng: random.Random, metric: MetricSpec, low: float, high: float) -> float:
    if high <= low:
        low, high = metric.low, metric.high
    return _round_value(rng.uniform(low, high), metric.decimals)


def _record(
    record_id: str,
    day: date,
    metric: MetricSpec,
    value: float,
    detail: str,
) -> dict[str, Any]:
    return {
        "id": record_id,
        "date": day.isoformat(),
        "type": metric.label,
        "value": _round_value(value, metric.decimals),
        "unit": metric.unit,
        "detail": detail,
        "metric": metric.key,
    }


def _other_metric(rng: random.Random, metric: MetricSpec) -> MetricSpec:
    pool = tuple(item for item in METRICS if item.key != metric.key)
    return rng.choice(pool)


def _triage(severity: float, abnormal_direction: int) -> str:
    """Map an effect size and its clinical direction to a workflow priority."""
    if abnormal_direction == 0:
        return "routine" if severity < 0.1 else "review"
    if severity >= 0.4:
        return "urgent"
    if severity >= 0.15:
        return "review"
    return "routine"


@dataclass(slots=True)
class SynthesizedSeed:
    """One generated QA seed before it is wrapped into :class:`QuestionSeed`."""

    question: str
    answer: str
    records: list[dict[str, Any]]
    evidence_ids: list[str]
    note_must_include: list[str]
    answer_type: str
    status: str
    metric_key: str


def _span(metric: MetricSpec) -> float:
    return metric.high - metric.low


def _delta_phrase(metric: MetricSpec, value: float) -> str:
    """Singular/plural-aware unit phrase for a difference or threshold."""
    if metric.delta_unit == "percentage points" and abs(value - 1.0) < 1e-9:
        return "percentage point"
    return metric.delta_unit


def _gen_longitudinal_comparison(rng: random.Random, day0: date) -> SynthesizedSeed:
    metric = rng.choice(METRICS)
    first = day0 + timedelta(days=rng.randrange(0, 25))
    second = first + timedelta(days=rng.randrange(1, 4))
    if metric.decimals == 0:
        step = float(rng.randrange(1, 12))
    else:
        step = round(rng.uniform(0.4, 3.5), 1)
    direction = rng.choice(("higher", "lower"))
    if direction == "higher":
        base = _sample_between(rng, metric, metric.low, metric.high - step)
        other = _round_value(base + step, metric.decimals)
    else:
        base = _sample_between(rng, metric, metric.low + step, metric.high)
        other = _round_value(base - step, metric.decimals)
    step = _round_value(abs(other - base), metric.decimals)

    first_id = f"{metric.key}-{first:%m%d}"
    second_id = f"{metric.key}-{second:%m%d}"
    records = [
        _record(first_id, first, metric, base, "Daily measurement"),
        _record(second_id, second, metric, other, "Daily measurement"),
    ]
    distractors: list[dict[str, Any]] = []
    outside = second + timedelta(days=rng.randrange(1, 4))
    if rng.random() < 0.75:
        distractors.append(
            _record(
                f"{metric.key}-{outside:%m%d}",
                outside,
                metric,
                _sample(rng, metric),
                "Outside the requested window",
            )
        )
    if rng.random() < 0.75:
        filler = _other_metric(rng, metric)
        distractors.append(
            _record(
                f"{filler.key}-{second:%m%d}",
                second,
                filler,
                _sample(rng, filler),
                "Different metric on the comparison day",
            )
        )
    if rng.random() < 0.5:
        distractors.append(
            _record(
                f"{metric.key}-{second:%m%d}-ctx",
                second,
                metric,
                _sample(rng, metric),
                "Same-day secondary reading (context mismatch)",
            )
        )
    if not distractors:
        distractors.append(
            _record(
                f"{metric.key}-{outside:%m%d}",
                outside,
                metric,
                _sample(rng, metric),
                "Outside the requested window",
            )
        )
    records.extend(distractors)

    step_text = _fmt(step, metric.decimals)
    delta_phrase = _delta_phrase(metric, step)
    severity = step / _span(metric)
    abnormal = 0
    if metric.higher_is_worse:
        abnormal = 1 if direction == "higher" else -1
    return SynthesizedSeed(
        question=(
            f"How many {delta_phrase} {direction} was the {metric.label} on "
            f"{second.isoformat()} than on {first.isoformat()}?"
        ),
        answer=f"{step_text} {delta_phrase}",
        records=records,
        evidence_ids=[first_id, second_id],
        note_must_include=[step_text, delta_phrase],
        answer_type="numeric-delta",
        status=_triage(severity, abnormal),
        metric_key=metric.key,
    )


def _gen_temporal_aggregation(rng: random.Random, day0: date) -> SynthesizedSeed:
    metric = rng.choice(METRICS)
    days = rng.choice((3, 4, 5))
    start = day0 + timedelta(days=rng.randrange(0, 25))
    window = [start + timedelta(days=offset) for offset in range(days)]
    total_mode = metric.key in COUNTABLE_METRICS and rng.random() < 0.4

    values: list[float] = []
    for _ in range(24):
        target = _sample(rng, metric)
        leaders = [_sample(rng, metric) for _ in range(days - 1)]
        tail = _round_value(days * target - sum(leaders), metric.decimals)
        if metric.low <= tail <= metric.high:
            values = [*leaders, tail]
            break
    if not values:
        values = [_sample(rng, metric) for _ in range(days)]
    rng.shuffle(values)

    ids = [f"{metric.key}-{day:%m%d}" for day in window]
    records = [
        _record(record_id, day, metric, value, "Daily measurement")
        for record_id, day, value in zip(ids, window, values, strict=True)
    ]
    before = start - timedelta(days=1)
    after = window[-1] + timedelta(days=1)
    distractors = [
        _record(
            f"{metric.key}-{before:%m%d}",
            before,
            metric,
            _sample(rng, metric),
            "Outside the requested window",
        ),
        _record(
            f"{metric.key}-{after:%m%d}",
            after,
            metric,
            _sample(rng, metric),
            "Outside the requested window",
        ),
    ]
    if rng.random() < 0.6:
        filler = _other_metric(rng, metric)
        distractors.append(
            _record(
                f"{filler.key}-{window[0]:%m%d}",
                window[0],
                filler,
                _sample(rng, filler),
                "Different metric inside the window",
            )
        )
    records.extend(distractors)

    if total_mode:
        total = _round_value(sum(values), metric.decimals)
        answer_value = total
        answer_text = f"{_fmt(answer_value, metric.decimals)} {metric.unit}"
        question = (
            f"What was the total {metric.label} across the {days} days from "
            f"{window[0].isoformat()} through {window[-1].isoformat()}?"
        )
        answer_type = "numeric-total"
    else:
        answer_value = _round_value(sum(values) / days, metric.decimals)
        answer_text = f"{_fmt(answer_value, metric.decimals)} {metric.unit}"
        question = (
            f"What was the average {metric.label} across the {days} days from "
            f"{window[0].isoformat()} through {window[-1].isoformat()}?"
        )
        answer_type = "numeric-average"

    midpoint = (metric.low + metric.high) / 2
    severity = abs(answer_value - midpoint) / (_span(metric) / 2) if not total_mode else 0.0
    abnormal = 0
    if not total_mode and metric.higher_is_worse:
        abnormal = 1 if answer_value > midpoint else -1
    return SynthesizedSeed(
        question=question,
        answer=answer_text,
        records=records,
        evidence_ids=ids,
        note_must_include=[_fmt(answer_value, metric.decimals), metric.unit],
        answer_type=answer_type,
        status=_triage(severity, abnormal),
        metric_key=metric.key,
    )


def _gen_cross_dimensional(rng: random.Random, day0: date) -> SynthesizedSeed:
    metric_a = rng.choice(METRICS)
    metric_b = _other_metric(rng, metric_a)
    days = rng.choice((3, 4))
    start = day0 + timedelta(days=rng.randrange(0, 25))
    window = [start + timedelta(days=offset) for offset in range(days)]
    target_index = rng.randrange(days)

    margin_a = max(_span(metric_a) * 0.06, 1.0 if metric_a.decimals == 0 else 0.4)
    peak = _sample_between(rng, metric_a, metric_a.low + margin_a, metric_a.high)
    values_a = [
        _sample_between(rng, metric_a, metric_a.low, max(metric_a.low, peak - margin_a))
        for _ in range(days)
    ]
    margin_b = max(_span(metric_b) * 0.06, 1.0 if metric_b.decimals == 0 else 0.4)
    trough = _sample_between(rng, metric_b, metric_b.low, metric_b.high - margin_b)
    values_b = [
        _sample_between(rng, metric_b, min(metric_b.high, trough + margin_b), metric_b.high)
        for _ in range(days)
    ]
    values_a[target_index] = peak
    values_b[target_index] = trough

    records: list[dict[str, Any]] = []
    ids_a: list[str] = []
    ids_b: list[str] = []
    for index, day in enumerate(window):
        id_a = f"{metric_a.key}-{day:%m%d}"
        id_b = f"{metric_b.key}-{day:%m%d}"
        ids_a.append(id_a)
        ids_b.append(id_b)
        records.append(_record(id_a, day, metric_a, values_a[index], "Daily measurement"))
        records.append(_record(id_b, day, metric_b, values_b[index], "Daily measurement"))

    target_day = window[target_index]
    return SynthesizedSeed(
        question=(
            f"Among the recorded days from {window[0].isoformat()} to {window[-1].isoformat()}, "
            f"on which day did the participant have both the highest {metric_a.label} "
            f"and the lowest {metric_b.label}?"
        ),
        answer=target_day.isoformat(),
        records=records,
        evidence_ids=[ids_a[target_index], ids_b[target_index]],
        note_must_include=[target_day.isoformat()],
        answer_type="date",
        status="review",
        metric_key=f"{metric_a.key}+{metric_b.key}",
    )


def _gen_threshold_detection(rng: random.Random, day0: date) -> SynthesizedSeed:
    metric = rng.choice(METRICS)
    days = rng.choice((5, 6, 7))
    start = day0 + timedelta(days=rng.randrange(0, 25))
    window = [start + timedelta(days=offset) for offset in range(days)]
    threshold = _sample_between(
        rng, metric, metric.low + _span(metric) * 0.2, metric.high - _span(metric) * 0.2
    )
    hits = rng.randrange(1, days)
    order = list(range(days))
    rng.shuffle(order)
    flagged = set(order[:hits])

    records: list[dict[str, Any]] = []
    evidence: list[str] = []
    for index, day in enumerate(window):
        record_id = f"{metric.key}-{day:%m%d}"
        if index in flagged:
            value = _sample_between(rng, metric, min(metric.high, threshold + 0.5), metric.high)
            detail = "Daily measurement"
            evidence.append(record_id)
        else:
            value = _sample_between(rng, metric, metric.low, max(metric.low, threshold - 0.5))
            detail = "Daily measurement"
        records.append(_record(record_id, day, metric, value, detail))
    if rng.random() < 0.6:
        filler = _other_metric(rng, metric)
        records.append(
            _record(
                f"{filler.key}-{window[0]:%m%d}",
                window[0],
                filler,
                _sample(rng, filler),
                "Different metric",
            )
        )

    noun = "days" if hits > 1 else "day"
    question = (
        f"On how many of the recorded days did the {metric.label} exceed "
        f"{_fmt(threshold, metric.decimals)} {metric.delta_unit}?"
    )
    severity = hits / days
    abnormal = 1 if metric.higher_is_worse else 0
    return SynthesizedSeed(
        question=question,
        answer=f"{hits} {noun}",
        records=records,
        evidence_ids=evidence,
        note_must_include=[str(hits), noun],
        answer_type="count",
        status=_triage(severity, abnormal),
        metric_key=metric.key,
    )


def _gen_extremum_identification(rng: random.Random, day0: date) -> SynthesizedSeed:
    metric = rng.choice(METRICS)
    days = rng.choice((4, 5, 6))
    start = day0 + timedelta(days=rng.randrange(0, 25))
    window = [start + timedelta(days=offset) for offset in range(days)]
    want_max = rng.random() < 0.5
    margin = max(_span(metric) * 0.06, 1.0 if metric.decimals == 0 else 0.4)

    if want_max:
        extreme = _sample_between(rng, metric, metric.low + margin, metric.high)
        rest_low, rest_high = metric.low, max(metric.low, extreme - margin)
    else:
        extreme = _sample_between(rng, metric, metric.low, metric.high - margin)
        rest_low, rest_high = min(metric.high, extreme + margin), metric.high
    values = [_sample_between(rng, metric, rest_low, rest_high) for _ in range(days)]
    target_index = rng.randrange(days)
    values[target_index] = extreme

    ids = [f"{metric.key}-{day:%m%d}" for day in window]
    records = [
        _record(record_id, day, metric, value, "Daily measurement")
        for record_id, day, value in zip(ids, window, values, strict=True)
    ]
    if rng.random() < 0.6:
        filler = _other_metric(rng, metric)
        records.append(
            _record(
                f"{filler.key}-{window[0]:%m%d}",
                window[0],
                filler,
                _sample(rng, filler),
                "Different metric",
            )
        )

    target_day = window[target_index]
    direction_word = "highest" if want_max else "lowest"
    severity = abs(extreme - (values[0] if target_index else values[1])) / _span(metric)
    abnormal = 0
    if metric.higher_is_worse:
        abnormal = 1 if want_max else -1
    return SynthesizedSeed(
        question=(
            f"Among the recorded days from {window[0].isoformat()} to {window[-1].isoformat()}, "
            f"on which day was the {metric.label} {direction_word}?"
        ),
        answer=target_day.isoformat(),
        records=records,
        evidence_ids=[ids[target_index]],
        note_must_include=[target_day.isoformat()],
        answer_type="date",
        status=_triage(severity, abnormal),
        metric_key=metric.key,
    )


def _gen_trend_classification(rng: random.Random, day0: date) -> SynthesizedSeed:
    metric = rng.choice(METRICS)
    days = rng.choice((4, 5, 6))
    start = day0 + timedelta(days=rng.randrange(0, 25))
    window = [start + timedelta(days=offset) for offset in range(days)]
    increasing = rng.random() < 0.5
    step_min = 1.0 if metric.decimals == 0 else 0.2
    usable = _span(metric) * 0.7
    per_step = usable / (days - 1)

    values: list[float] = []
    cursor = metric.low + _span(metric) * 0.05 if increasing else metric.high - _span(metric) * 0.05
    for _ in range(days):
        values.append(_round_value(cursor, metric.decimals))
        delta = rng.uniform(step_min, max(step_min, per_step))
        cursor = cursor + delta if increasing else cursor - delta
    values = [
        _round_value(min(max(value, metric.low), metric.high), metric.decimals) for value in values
    ]
    for index in range(1, days):
        if increasing and values[index] <= values[index - 1]:
            values[index] = _round_value(min(metric.high, values[index - 1] + step_min), metric.decimals)
        elif not increasing and values[index] >= values[index - 1]:
            values[index] = _round_value(max(metric.low, values[index - 1] - step_min), metric.decimals)

    ids = [f"{metric.key}-{day:%m%d}" for day in window]
    records = [
        _record(record_id, day, metric, value, "Daily measurement")
        for record_id, day, value in zip(ids, window, values, strict=True)
    ]
    filler = _other_metric(rng, metric)
    records.append(
        _record(
            f"{filler.key}-{window[0]:%m%d}",
            window[0],
            filler,
            _sample(rng, filler),
            "Different metric",
        )
    )

    answer = "increasing" if increasing else "decreasing"
    severity = abs(values[-1] - values[0]) / _span(metric)
    abnormal = 0
    if metric.higher_is_worse:
        abnormal = 1 if increasing else -1
    return SynthesizedSeed(
        question=(
            f"Across the {days} recorded days from {window[0].isoformat()} to "
            f"{window[-1].isoformat()}, did the {metric.label} trend upward or downward?"
        ),
        answer=answer,
        records=records,
        evidence_ids=ids,
        note_must_include=[answer],
        answer_type="label",
        status=_triage(severity, abnormal),
        metric_key=metric.key,
    )


def _gen_range_computation(rng: random.Random, day0: date) -> SynthesizedSeed:
    metric = rng.choice(METRICS)
    days = rng.choice((4, 5, 6))
    start = day0 + timedelta(days=rng.randrange(0, 25))
    window = [start + timedelta(days=offset) for offset in range(days)]
    margin = max(_span(metric) * 0.08, 1.0 if metric.decimals == 0 else 0.5)
    low_value = _sample_between(rng, metric, metric.low, metric.high - margin * 2)
    high_value = _sample_between(rng, metric, min(metric.high, low_value + margin * 2), metric.high)
    values = [_sample_between(rng, metric, low_value, high_value) for _ in range(days)]
    low_index = rng.randrange(days)
    high_index = rng.choice([index for index in range(days) if index != low_index])
    values[low_index] = low_value
    values[high_index] = high_value

    ids = [f"{metric.key}-{day:%m%d}" for day in window]
    records = [
        _record(record_id, day, metric, value, "Daily measurement")
        for record_id, day, value in zip(ids, window, values, strict=True)
    ]
    if rng.random() < 0.6:
        filler = _other_metric(rng, metric)
        records.append(
            _record(
                f"{filler.key}-{window[0]:%m%d}",
                window[0],
                filler,
                _sample(rng, filler),
                "Different metric",
            )
        )

    spread = _round_value(high_value - low_value, metric.decimals)
    return SynthesizedSeed(
        question=(
            f"What was the range (highest minus lowest) of the {metric.label} across the "
            f"{days} recorded days from {window[0].isoformat()} to {window[-1].isoformat()}?"
        ),
        answer=f"{_fmt(spread, metric.decimals)} {_delta_phrase(metric, spread)}",
        records=records,
        evidence_ids=[ids[high_index], ids[low_index]],
        note_must_include=[_fmt(spread, metric.decimals), _delta_phrase(metric, spread)],
        answer_type="numeric-range",
        status=_triage(spread / _span(metric), 0),
        metric_key=metric.key,
    )


SKILLS: tuple[str, ...] = (
    "longitudinal-comparison",
    "temporal-aggregation",
    "cross-dimensional-reasoning",
    "threshold-detection",
    "extremum-identification",
    "trend-classification",
    "range-computation",
)

_GENERATORS: dict[str, Callable[[random.Random, date], SynthesizedSeed]] = {
    "longitudinal-comparison": _gen_longitudinal_comparison,
    "temporal-aggregation": _gen_temporal_aggregation,
    "cross-dimensional-reasoning": _gen_cross_dimensional,
    "threshold-detection": _gen_threshold_detection,
    "extremum-identification": _gen_extremum_identification,
    "trend-classification": _gen_trend_classification,
    "range-computation": _gen_range_computation,
}

_AGE_BANDS: tuple[str, ...] = ("young-adult", "adult", "older-adult")


def _surface_for(index: int) -> str:
    """Assign a GUI surface deterministically, spread across reasoning skills.

    The surface only changes how the environment is rendered. It never changes
    the evidence set, the gold answer, or the verifier, so switching surfaces is
    a pure presentation change rather than a new task.
    """
    return SURFACES[(index + index // len(SKILLS)) % len(SURFACES)]


def generate_seeds(count: int, *, master_seed: int = 20261012) -> list[QuestionSeed]:
    """Generate ``count`` distinct QA seeds deterministically from ``master_seed``."""
    if count < 1:
        raise ValueError("count must be a positive integer")
    rng = random.Random(master_seed)
    seeds: list[QuestionSeed] = []
    for index in range(count):
        skill = SKILLS[index % len(SKILLS)]
        day0 = date(2023, 1, 1) + timedelta(days=rng.randrange(0, 730))
        synth = _GENERATORS[skill](rng, day0)
        participant_number = 1001 + (index % 250)
        seeds.append(
            QuestionSeed(
                seed_id=f"synth-{index:05d}",
                participant_id=f"HENV-{participant_number:04d}",
                question=synth.question,
                answer=synth.answer,
                category=skill,
                records=synth.records,
                evidence_ids=synth.evidence_ids,
                metadata={
                    "display_name": f"Synthetic Participant {participant_number}",
                    "age_band": _AGE_BANDS[index % len(_AGE_BANDS)],
                    "required_status": synth.status,
                    "surface": _surface_for(index),
                    "note_must_include": synth.note_must_include,
                    "skill": skill,
                    "metric": synth.metric_key,
                    "answer_type": synth.answer_type,
                    "synthetic": True,
                    "synthetic_record_state": True,
                    "upstream_payload_redistributed": False,
                    "generator": SEEDGEN_VERSION,
                    "master_seed": master_seed,
                },
            )
        )
    return seeds


def write_seed_file(seeds: list[QuestionSeed], path: str) -> int:
    """Write seeds as JSONL and return the number of lines written."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(seed.to_dict(), ensure_ascii=False) + "\n" for seed in seeds)
    destination.write_text(payload, encoding="utf-8")
    return len(seeds)
