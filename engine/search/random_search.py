"""Random search (SPEC §6.3): uniform action/amount sampling, NO fitness
feedback and no corpus/mutation state — every candidate is drawn i.i.d. This
is the honest baseline for the §12 benchmark, so it deliberately shares the
exact execution path, budget accounting, and action space with
guided_search.py; only "what to try next" differs.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from engine.actions import Candidate
from engine.bridge import ExecutionBridge
from engine.evaluator import Evaluation, Evaluator
from engine.observer import Observer
from engine.search.mutations import ActionSpace, random_candidate


@dataclass
class SearchResult:
    exploits: list[tuple[Candidate, Evaluation]] = field(default_factory=list)
    candidates_evaluated: int = 0
    # SPEC §12 primary metric: candidates evaluated before the first
    # qualifying exploit. None if the budget ran out without one.
    candidates_to_first_exploit: int | None = None


def run_random_search(
    bridge: ExecutionBridge,
    evaluator: Evaluator,
    observer: Observer,
    space: ActionSpace,
    rng: random.Random,
    budget_candidates: int,
    stop_on_first: bool = False,
) -> SearchResult:
    """SPEC §6.1 candidate lifecycle, specialized to uniform sampling. Budget
    is measured in candidates, not seconds. Keeps searching past the first
    exploit (to find multiple / shorter ones) unless `stop_on_first`."""
    result = SearchResult()

    for i in range(1, budget_candidates + 1):
        candidate = random_candidate(space, rng)

        # SPEC §5 step order: submit -> capture receipt -> read state -> restore.
        exec_result = bridge.execute(candidate)
        state = observer.read()
        ev = evaluator.evaluate(exec_result, state)
        bridge.restore()

        result.candidates_evaluated = i
        if ev.is_exploit:
            if result.candidates_to_first_exploit is None:
                result.candidates_to_first_exploit = i
            result.exploits.append((candidate, ev))
            if stop_on_first:
                break
        # No corpus/fitness bookkeeping here by design (SPEC §6.3) — an
        # interesting-but-non-qualifying candidate is simply discarded.

    return result
