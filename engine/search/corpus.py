"""Corpus of candidates worth mutating further (SPEC §6.1, §6.3). Dedupe is
structural — `Candidate` is itself a frozen, hashable dataclass (see
engine/actions.py) — so a mutation that lands back on something already
tried never inflates the corpus.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from engine.actions import Action, ActionType, AmountRule, Candidate
from engine.search.mutations import ActionSpace, random_candidate


@dataclass(frozen=True)
class CorpusEntry:
    candidate: Candidate
    fitness: float


class Corpus:
    def __init__(self) -> None:
        self._entries: dict[Candidate, float] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def add(self, candidate: Candidate, fitness: float) -> bool:
        """Record/refresh a candidate's fitness. Returns True iff this was a
        structurally new candidate (the dedupe signal)."""
        is_new = candidate not in self._entries
        if is_new or fitness > self._entries[candidate]:
            self._entries[candidate] = fitness
        return is_new

    def seed(self, candidates: list[Candidate], fitness: float = 0.0) -> None:
        for c in candidates:
            self.add(c, fitness)

    @property
    def entries(self) -> list[CorpusEntry]:
        return [CorpusEntry(c, f) for c, f in self._entries.items()]

    def select(self, rng: random.Random) -> Candidate:
        """Uniform-random parent selection — the baseline `select()` random
        search uses directly (SPEC §6.1 pseudocode). guided_search.py
        (Phase 5) layers fitness-weighted selection on top of `entries`
        instead of replacing this method (SPEC §6.3)."""
        if not self._entries:
            raise ValueError("cannot select from an empty corpus")
        return rng.choice(list(self._entries.keys()))


def seed_corpus(space: ActionSpace, rng: random.Random, n_random: int = 20) -> Corpus:
    """"A handful of hand-shaped + random seeds" (SPEC §6.1). The hand-shaped
    seeds are generic, PLAUSIBLE shapes with round/untuned parameters —
    never the tuned Phase-2 reference sequence (SPEC §14: no hardcoded
    winning sequence in the search path)."""
    corpus = Corpus()

    hand_shaped = [
        Candidate(flash_token=space.usd, flash_amount=100_000 * 10**18, actions=()),
        Candidate(
            flash_token=space.usd,
            flash_amount=100_000 * 10**18,
            actions=(Action(ActionType.SWAP_USD_FOR_COL, space.amm, AmountRule.PCT_BALANCE, 5000),),
        ),
        Candidate(
            flash_token=space.usd,
            flash_amount=100_000 * 10**18,
            actions=(
                Action(ActionType.SWAP_USD_FOR_COL, space.amm, AmountRule.PCT_BALANCE, 5000),
                Action(ActionType.DEPOSIT_COL, space.lending, AmountRule.PCT_BALANCE, 5000),
            ),
        ),
        Candidate(
            flash_token=space.usd,
            flash_amount=100_000 * 10**18,
            actions=(
                Action(ActionType.SWAP_USD_FOR_COL, space.amm, AmountRule.PCT_BALANCE, 5000),
                Action(ActionType.DEPOSIT_COL, space.lending, AmountRule.PCT_BALANCE, 5000),
                Action(ActionType.BORROW_USD, space.lending, AmountRule.PCT_BORROW_CAPACITY, 5000),
            ),
        ),
        Candidate(
            flash_token=space.col,
            flash_amount=100_000 * 10**18,
            actions=(Action(ActionType.DEPOSIT_COL, space.lending, AmountRule.PCT_BALANCE, 5000),),
        ),
    ]
    corpus.seed(hand_shaped)
    corpus.seed([random_candidate(space, rng) for _ in range(n_random)])
    return corpus
