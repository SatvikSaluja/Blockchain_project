import random

import pytest

from engine.actions import Action, ActionType, AmountRule, Candidate
from engine.search.corpus import Corpus, seed_corpus
from engine.search.mutations import ActionSpace

SPACE = ActionSpace(
    usd="0x1000000000000000000000000000000000000001",
    col="0x2000000000000000000000000000000000000002",
    amm="0x3000000000000000000000000000000000000003",
    lending="0x4000000000000000000000000000000000000004",
)


def _candidate(param: int) -> Candidate:
    return Candidate(
        flash_token=SPACE.usd,
        flash_amount=1_000 * 10**18,
        actions=(Action(ActionType.SWAP_USD_FOR_COL, SPACE.amm, AmountRule.FIXED, param),),
    )


def test_add_dedupes_structurally_identical_candidates():
    corpus = Corpus()
    c = _candidate(1)
    assert corpus.add(c, fitness=1.0) is True
    assert corpus.add(c, fitness=2.0) is False  # same candidate again -> dedupe hit
    assert len(corpus) == 1


def test_add_keeps_best_seen_fitness_on_dedupe():
    corpus = Corpus()
    c = _candidate(1)
    corpus.add(c, fitness=1.0)
    corpus.add(c, fitness=5.0)
    corpus.add(c, fitness=2.0)  # worse than best-seen -> kept at 5.0
    assert corpus.entries[0].fitness == 5.0


def test_select_raises_on_empty_corpus():
    corpus = Corpus()
    with pytest.raises(ValueError):
        corpus.select(random.Random(0))


def test_select_samples_all_members_over_many_draws():
    corpus = Corpus()
    candidates = [_candidate(i) for i in range(5)]
    for c in candidates:
        corpus.add(c, fitness=0.0)

    rng = random.Random(42)
    seen = {corpus.select(rng) for _ in range(500)}
    assert seen == set(candidates)


def test_seed_corpus_contains_hand_shaped_and_random_entries():
    rng = random.Random(99)
    corpus = seed_corpus(SPACE, rng, n_random=20)
    # 5 hand-shaped + 20 random, collisions astronomically unlikely.
    assert len(corpus) == 25
