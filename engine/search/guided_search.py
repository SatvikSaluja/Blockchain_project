"""Guided search (SPEC §6.3): fitness-weighted parent selection (softmax)
with an epsilon-uniform exploration fraction, plus novelty retention via the
corpus/fitness function. Shares the exact execution path, budget accounting,
and action space with random_search.py — only "what to try next" differs,
which is what makes the §12 head-to-head fair.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

from engine.actions import Candidate
from engine.bridge import ExecResult, ExecutionBridge
from engine.evaluator import Evaluation, Evaluator
from engine.observer import Observer
from engine.search.corpus import Corpus, seed_corpus
from engine.search.mutations import ActionSpace, mutate


@dataclass
class SearchResult:
    exploits: list[tuple[Candidate, Evaluation, ExecResult]] = field(default_factory=list)
    candidates_evaluated: int = 0
    candidates_to_first_exploit: Optional[int] = None
    corpus_size: int = 0


def select_weighted(corpus: Corpus, rng: random.Random, epsilon: float) -> Candidate:
    """Parent selection: probability ∝ softmax(fitness), with an epsilon
    fraction of uniform picks to preserve exploration (SPEC §6.3)."""
    entries = corpus.entries
    if not entries:
        raise ValueError("cannot select from an empty corpus")
    if rng.random() < epsilon:
        return rng.choice(entries).candidate

    max_score = max(e.fitness for e in entries)  # numerical stability
    weights = [math.exp(e.fitness - max_score) for e in entries]
    return rng.choices(entries, weights=weights, k=1)[0].candidate


def run_guided_search(
    bridge: ExecutionBridge,
    evaluator: Evaluator,
    observer: Observer,
    space: ActionSpace,
    rng: random.Random,
    budget_candidates: int,
    stop_on_first: bool = False,
    corpus: Optional[Corpus] = None,
) -> SearchResult:
    """SPEC §6.1 candidate lifecycle: fitness-weighted select -> mutate ->
    execute -> evaluate -> (save exploit | grow corpus). `evaluator` must be
    constructed with a fitness_fn (engine/search/fitness.py's
    WeightedFitness) for the selection weighting to mean anything — with the
    Evaluator default placeholder this degrades to a fitness-agnostic
    mutation walk, which is not what Phase 5 is for."""
    result = SearchResult()
    corpus = corpus if corpus is not None else seed_corpus(space, rng)
    epsilon = evaluator.scenario.search.selection_epsilon

    for i in range(1, budget_candidates + 1):
        parent = select_weighted(corpus, rng, epsilon)
        candidate = mutate(parent, rng, space)

        # SPEC §5 step order: submit -> capture receipt -> read state -> restore.
        exec_result = bridge.execute(candidate)
        state = observer.read()
        ev = evaluator.evaluate(candidate, exec_result, state)
        bridge.restore()

        result.candidates_evaluated = i
        if ev.is_exploit:
            if result.candidates_to_first_exploit is None:
                result.candidates_to_first_exploit = i
            result.exploits.append((candidate, ev, exec_result))
            if stop_on_first:
                break
        elif ev.is_interesting:
            corpus.add(candidate, ev.fitness)

    result.corpus_size = len(corpus)
    return result
