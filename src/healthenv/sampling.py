"""Stratified sampling shared by every evaluation driver.

Two scripts sample the compiled corpus: ``scripts/harness_eval.py`` (agent
harnesses) and ``scripts/browser_batch.py`` (the in-browser GUI proof). They
originally carried independent copies of the same function, and the copies
diverged -- one was fixed for the defect below and the other was not, which
means one of the two artifacts in the repository was reporting a surface
breakdown produced by a biased sampler. The fix is to have exactly one
implementation, so the property is proved once and inherited everywhere.

The defect worth recording, because it is silent and it produced plausible
numbers: a flat round-robin over ``(surface, status, skill)`` cells sorts the
cells alphabetically, and ``clinical-ledger`` outranks ``timeline``. For any
``limit`` below the cell count, every pick lands in the alphabetically-first
cell, so the sample collapses onto a single surface while still looking like a
stratified draw. Measured on the 1200-task corpus, the original implementation
returned 12/12 ``clinical-ledger`` tasks for ``--limit 12``.

The sampler here interleaves surfaces on every pick, so a small limit spreads
across all three GUI surfaces, and within a surface it still walks the
``(status, skill)`` cells round-robin rather than in file order.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

CellKey = tuple[str, str, str]


def cell_key(task: object) -> CellKey:
    """The ``(surface, required status, reasoning skill)`` cell for a task."""
    source = getattr(task, "source", {})
    verifier = getattr(task, "verifier", {})
    return (
        str(source.get("surface", "timeline")),
        str(verifier.get("required_status", "review")),
        str(source.get("category", "unknown")),
    )


def stratified_sample(
    tasks: list[T],
    limit: int,
    *,
    key: Callable[[T], CellKey] = cell_key,
) -> list[T]:
    """Pick up to ``limit`` tasks spread over surfaces, then over cells.

    Surfaces are interleaved on every pick, so ``limit`` smaller than the
    number of cells still covers every surface instead of collapsing onto
    whichever surface sorts first. Within a surface the ``(status, skill)``
    cells are walked round-robin, one task per cell per pass, so the draw is
    not dominated by whichever cell happens to be largest.
    """
    cells: dict[CellKey, list[T]] = {}
    for task in tasks:
        cells.setdefault(key(task), []).append(task)
    if not cells:
        return []

    surfaces = sorted({cell[0] for cell in cells})

    def surface_queue(surface: str) -> list[T]:
        """One surface's tasks, taken cell by cell in round-robin order."""
        keys = sorted(cell for cell in cells if cell[0] == surface)
        queue: list[T] = []
        depth = 0
        while True:
            progressed = False
            for cell in keys:
                bucket = cells[cell]
                if depth < len(bucket):
                    queue.append(bucket[depth])
                    progressed = True
            if not progressed:
                return queue
            depth += 1

    queues = [surface_queue(surface) for surface in surfaces]
    picked: list[T] = []
    index = 0
    while len(picked) < limit:
        advanced = False
        for queue in queues:
            if index < len(queue):
                picked.append(queue[index])
                advanced = True
                if len(picked) >= limit:
                    break
        if not advanced:
            break
        index += 1
    return picked
