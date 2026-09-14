"""Unit tests with a tiny fake bridge/evaluator/observer, mirroring
tests/test_random_search.py. The real head-to-head vs random search runs
against a live Anvil in experiments/random_vs_guided.py (Task 26)."""

import random
from pathlib import Path

import pytest

from engine.evaluator import Evaluation
from engine.scenario import Scenario
from engine.search.corpus import Corpus
from engine.search.guided_search import run_guided_search, select_weighted
from engine.search.mutations import ActionSpace, random_candidate

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "vulnerable.json"

SPACE = ActionSpace(
    usd="0x1000000000000000000000000000000000000001",
    col="0x2000000000000000000000000000000000000002",
    amm="0x3000000000000000000000000000000000000003",
    lending="0x4000000000000000000000000000000000000004",
)


def test_select_weighted_favors_higher_fitness_entries():
    rng = random.Random(0)
    low = random_candidate(SPACE, random.Random(1))
    high = random_candidate(SPACE, random.Random(2))
    corpus = Corpus()
    corpus.add(low, fitness=0.0)
    corpus.add(high, fitness=10.0)

    picks = [select_weighted(corpus, rng, epsilon=0.0) for _ in range(500)]
    assert picks.count(high) > picks.count(low) * 5


def test_select_weighted_epsilon_one_is_fully_uniform():
    rng = random.Random(0)
    low = random_candidate(SPACE, random.Random(1))
    high = random_candidate(SPACE, random.Random(2))
    corpus = Corpus()
    corpus.add(low, fitness=0.0)
    corpus.add(high, fitness=10.0)

    picks = [select_weighted(corpus, rng, epsilon=1.0) for _ in range(500)]
    ratio = picks.count(high) / len(picks)
    assert 0.35 < ratio < 0.65  # roughly 50/50 when fully uniform


def test_select_weighted_raises_on_empty_corpus():
    with pytest.raises(ValueError):
        select_weighted(Corpus(), random.Random(0), epsilon=0.1)


class FakeBridge:
    def __init__(self):
        self.executed = []
        self.restored_count = 0

    def execute(self, candidate):
        self.executed.append(candidate)
        return "exec_result"

    def restore(self):
        self.restored_count += 1


class FakeObserver:
    def read(self):
        return "state"


class FakeEvaluator:
    """`.scenario` is the real loaded Scenario (cheap, no Anvil needed) so
    run_guided_search can read selection_epsilon from it, same as the real
    Evaluator does."""

    def __init__(self, scenario, exploit_at=frozenset(), interesting_at=frozenset()):
        self.scenario = scenario
        self.exploit_at = exploit_at
        self.interesting_at = interesting_at
        self.calls = 0

    def evaluate(self, candidate, exec_result, state):
        self.calls += 1
        is_exploit = self.calls in self.exploit_at
        is_interesting = (not is_exploit) and self.calls in self.interesting_at
        return Evaluation(
            is_exploit=is_exploit,
            is_interesting=is_interesting,
            fitness=float(self.calls),
            attacker_profit_usd=0,
            protocol_bad_debt_usd=0,
            violated_property="debt_exceeds_collateral_at_reference_price" if is_exploit else None,
        )


def test_guided_search_stops_at_budget_and_grows_corpus_on_interesting_hits():
    scenario = Scenario.load(SCENARIO_PATH)
    bridge = FakeBridge()
    evaluator = FakeEvaluator(scenario, interesting_at={2, 4, 6})
    result = run_guided_search(bridge, evaluator, FakeObserver(), SPACE, random.Random(5), budget_candidates=20)

    assert result.candidates_evaluated == 20
    assert len(bridge.executed) == 20
    assert bridge.restored_count == 20
    # seed_corpus default: 5 hand-shaped + 20 random = 25. The 3
    # "interesting" adds may or may not all be structurally new (a mutation
    # can land back on its own parent, e.g. insert_action at the MAX_ACTIONS
    # cap is a no-op) — dedupe correctly not double-counting those is the
    # point, so only assert growth is possible, not its exact size.
    assert result.corpus_size >= 25


def test_guided_search_records_first_exploit_and_keeps_searching():
    scenario = Scenario.load(SCENARIO_PATH)
    bridge = FakeBridge()
    evaluator = FakeEvaluator(scenario, exploit_at={10, 15})
    result = run_guided_search(bridge, evaluator, FakeObserver(), SPACE, random.Random(6), budget_candidates=20)

    assert result.candidates_to_first_exploit == 10
    assert len(result.exploits) == 2
    assert result.candidates_evaluated == 20


def test_guided_search_stop_on_first_halts_immediately():
    scenario = Scenario.load(SCENARIO_PATH)
    bridge = FakeBridge()
    evaluator = FakeEvaluator(scenario, exploit_at={3})
    result = run_guided_search(
        bridge, evaluator, FakeObserver(), SPACE, random.Random(7), budget_candidates=20, stop_on_first=True
    )

    assert result.candidates_to_first_exploit == 3
    assert result.candidates_evaluated == 3
