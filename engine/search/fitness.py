"""Weighted-sum fitness (SPEC §6.4). Ranks candidates for further
exploration — it does NOT declare an exploit (that's Evaluator/§7). Weights
live in scenario.json (`search.fitnessWeights`) so ablations are config-only.

This is fitness-guided evolutionary search, not RL: `WeightedFitness` is a
plain scoring function of the current candidate/state, with no notion of
reward-over-time, value function, or policy (SPEC §0, §14).
"""

from __future__ import annotations

from engine.actions import Candidate
from engine.bridge import ExecResult
from engine.observer import EconState
from engine.scenario import Scenario
from engine.search.mutations import ActionSpace
from engine.search.novelty import NoveltyTracker


class WeightedFitness:
    """Stateful callable matching Evaluator's `FitnessFn` signature
    `(candidate, state, exec_result, profit_usd, bad_debt_usd) -> float`.
    Owns the one NoveltyTracker for a whole search run — construct exactly
    once per run, not per candidate, and always pass the SAME instance to
    every Evaluator used in that run."""

    def __init__(self, scenario: Scenario, space: ActionSpace, novelty_tracker: NoveltyTracker):
        self.weights = scenario.search.fitness_weights
        self.collateral_factor_bps = scenario.lending.collateral_factor_bps
        # Profit/bad-debt normalize against initial capital (a scale already
        # in the scenario) so they land in the same rough O(1) magnitude as
        # the other signals instead of swamping them as raw 1e18-scaled USD.
        self.capital_scale = max(1, scenario.attacker.initial_capital_usd)
        self.space = space
        self.novelty_tracker = novelty_tracker

    def __call__(
        self, candidate: Candidate, state: EconState, result: ExecResult, _profit_usd: int, bad_debt_usd: int
    ) -> float:
        # `_profit_usd` (Evaluator's net-of-initial-capital number) is part
        # of the FitnessFn protocol but deliberately unused here — see
        # _raw_captured_usd's docstring.
        w = self.weights
        return (
            w.price_deviation * self._price_deviation(state)
            + w.capacity_per_capital * self._capacity_per_capital(candidate, state)
            + w.bad_debt * (bad_debt_usd / self.capital_scale)
            + w.profit * (self._raw_captured_usd(state) / self.capital_scale)
            + w.novelty * self.novelty_tracker.score(state)
        )

    def _raw_captured_usd(self, state: EconState) -> int:
        """"progress toward profit" (§6.4), NOT Evaluator's net profit_usd.

        Evaluator's profit_usd deducts initial_capital_usd — a near-constant
        ~-capital_scale for every candidate that hasn't yet closed the full
        flash-loan loop, since it hasn't captured anything back. Reusing
        that number here would give every non-qualifying candidate almost
        the same deeply-negative fitness regardless of real progress,
        drowning out the signal fitness is supposed to provide (verified
        empirically: it made every unevaluated placeholder-fitness seed
        permanently outrank every genuine discovery). Raw captured USD
        floors at 0 for "nothing captured yet" and rises with real
        progress, which is what a ranking signal needs.
        """
        return state.attacker_usd + (state.attacker_col * state.reference_price) // 10**18

    def _price_deviation(self, state: EconState) -> float:
        """|oracle_price - reference_price| / reference_price."""
        if state.reference_price == 0:
            return 0.0
        return abs(state.oracle_price - state.reference_price) / state.reference_price

    def _capacity_per_capital(self, candidate: Candidate, state: EconState) -> float:
        """Δborrow_capacity / capital_deployed — "unusually cheap credit."
        Uses the on-chain (manipulable) oracle price deliberately: this is a
        search heuristic rewarding states where manipulation is inflating
        capacity, not a solvency judgment (that stays reference-priced, in
        Evaluator)."""
        capital_deployed = self._capital_deployed_usd(candidate, state)
        if capital_deployed <= 0:
            return 0.0
        collateral_value_usd = (state.collateral_col * state.oracle_price) // 10**18
        max_debt_usd = (collateral_value_usd * self.collateral_factor_bps) // 10**4
        borrow_capacity_usd = max(0, max_debt_usd - state.debt_usd)
        return borrow_capacity_usd / capital_deployed

    def _capital_deployed_usd(self, candidate: Candidate, state: EconState) -> int:
        if candidate.flash_token.lower() == self.space.col.lower():
            return (candidate.flash_amount * state.reference_price) // 10**18
        return candidate.flash_amount  # flash_token == USD, already USD-denominated
