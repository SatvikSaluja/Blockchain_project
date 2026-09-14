"""Evaluator (SPEC §7): judges profit and solvency using an INDEPENDENT,
fixed `reference_price` — never the contracts' own (manipulable) oracle.
Otherwise a manipulated oracle would let the evaluator report phantom
profit (circular).

The fitness score used for parent *selection* is a separate, pluggable
concern (Phase 5, engine/search/fitness.py) — this module only guarantees
the two rules that don't depend on it: a reverted candidate always scores
-inf (§6.4), and `is_exploit` is exactly the SPEC §7 four-part test.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from engine.actions import Candidate
from engine.bridge import ExecResult
from engine.observer import EconState
from engine.scenario import Scenario

GWEI = 10**9
VIOLATED_PROPERTY = "debt_exceeds_collateral_at_reference_price"

FitnessFn = Callable[[Candidate, EconState, ExecResult, int, int], float]


def _default_fitness(candidate: Candidate, state: EconState, result: ExecResult, profit_usd: int, bad_debt_usd: int) -> float:
    """Placeholder used until Phase 5 wires in the real weighted signal set
    (engine/search/fitness.py: price deviation, capacity/capital, bad debt,
    profit, novelty). Random search (Phase 4) never reads this field, so a
    coarse proxy is fine here."""
    return float(profit_usd + bad_debt_usd)


@dataclass(frozen=True)
class Evaluation:
    is_exploit: bool
    is_interesting: bool
    fitness: float
    attacker_profit_usd: int
    protocol_bad_debt_usd: int
    violated_property: str | None


class Evaluator:
    def __init__(self, scenario: Scenario, fitness_fn: FitnessFn = _default_fitness):
        self.scenario = scenario
        self.fitness_fn = fitness_fn

    def evaluate(self, candidate: Candidate, result: ExecResult, state: EconState) -> Evaluation:
        if result.reverted:
            # A reverted tx's state changes never persisted — not an
            # exploit, and not worth keeping in the corpus either.
            return Evaluation(
                is_exploit=False,
                is_interesting=False,
                fitness=-math.inf,
                attacker_profit_usd=0,
                protocol_bad_debt_usd=0,
                violated_property=None,
            )

        profit_usd = self._attacker_profit_usd(result, state)
        bad_debt_usd = max(0, state.debt_usd - self._collateral_usd_at_reference(state))

        # SPEC §7 criteria 3 & 4 (1 & 2 are implied by a non-revert, per
        # FlashLender's balance-delta enforcement).
        is_exploit = profit_usd > 0 and bad_debt_usd > 0

        return Evaluation(
            is_exploit=is_exploit,
            is_interesting=not is_exploit,  # any executed, non-qualifying tx is worth exploring further
            fitness=self.fitness_fn(candidate, state, result, profit_usd, bad_debt_usd),
            attacker_profit_usd=profit_usd,
            protocol_bad_debt_usd=bad_debt_usd,
            violated_property=VIOLATED_PROPERTY if is_exploit else None,
        )

    def _collateral_usd_at_reference(self, state: EconState) -> int:
        return (state.collateral_col * state.reference_price) // 10**18

    def _attacker_profit_usd(self, result: ExecResult, state: EconState) -> int:
        liquid_usd = state.attacker_usd + (state.attacker_col * state.reference_price) // 10**18
        gas_cost_usd = (
            result.gas_used * self.scenario.gas.gas_price_gwei * GWEI * self.scenario.gas.eth_price_usd
        ) // 10**18
        return liquid_usd - self.scenario.attacker.initial_capital_usd - gas_cost_usd
