"""Unit test with a tiny fake bridge/evaluator/observer — no real Anvil, so
this stays fast. The real discovery run against a live deployment is
Task 22 (tests/test_discovery.py, marked `discovery`)."""

import random

from engine.evaluator import Evaluation
from engine.search.mutations import ActionSpace
from engine.search.random_search import run_random_search

SPACE = ActionSpace(
    usd="0x1000000000000000000000000000000000000001",
    col="0x2000000000000000000000000000000000000002",
    amm="0x3000000000000000000000000000000000000003",
    lending="0x4000000000000000000000000000000000000004",
)


class FakeBridge:
    def __init__(self):
        self.executed = []
        self.restored_count = 0

    def execute(self, candidate):
        self.executed.append(candidate)
        return "exec_result_placeholder"

    def restore(self):
        self.restored_count += 1


class FakeObserver:
    def read(self):
        return "state_placeholder"


class FakeEvaluator:
    """Declares the Nth-evaluated candidate (1-indexed) an exploit for every
    N in `exploit_at`; everything else is neither interesting nor an
    exploit — matches random_search's "no corpus state" design."""

    def __init__(self, exploit_at: set[int]):
        self.exploit_at = exploit_at
        self.calls = 0

    def evaluate(self, exec_result, state):
        self.calls += 1
        is_exploit = self.calls in self.exploit_at
        return Evaluation(
            is_exploit=is_exploit,
            is_interesting=False,
            fitness=0.0,
            attacker_profit_usd=0,
            protocol_bad_debt_usd=0,
            violated_property="debt_exceeds_collateral_at_reference_price" if is_exploit else None,
        )


def test_stops_at_budget_and_counts_every_candidate():
    bridge = FakeBridge()
    result = run_random_search(
        bridge, FakeEvaluator(exploit_at=set()), FakeObserver(), SPACE, random.Random(1), budget_candidates=50
    )

    assert result.candidates_evaluated == 50
    assert len(bridge.executed) == 50
    assert bridge.restored_count == 50
    assert result.exploits == []
    assert result.candidates_to_first_exploit is None


def test_records_first_exploit_index_and_keeps_searching_past_it():
    bridge = FakeBridge()
    result = run_random_search(
        bridge, FakeEvaluator(exploit_at={10, 30}), FakeObserver(), SPACE, random.Random(2), budget_candidates=50
    )

    assert result.candidates_to_first_exploit == 10
    assert len(result.exploits) == 2  # SPEC §6.1: keep searching, don't early-exit by default
    assert result.candidates_evaluated == 50


def test_stop_on_first_halts_the_loop_immediately():
    bridge = FakeBridge()
    result = run_random_search(
        bridge,
        FakeEvaluator(exploit_at={5}),
        FakeObserver(),
        SPACE,
        random.Random(3),
        budget_candidates=50,
        stop_on_first=True,
    )

    assert result.candidates_to_first_exploit == 5
    assert result.candidates_evaluated == 5
    assert len(bridge.executed) == 5
