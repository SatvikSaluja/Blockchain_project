from pathlib import Path

import pytest

from engine.actions import Action, ActionType, AmountRule, Candidate
from engine.bridge import ExecResult
from engine.observer import EconState
from engine.scenario import Scenario
from engine.search.fitness import WeightedFitness
from engine.search.mutations import ActionSpace
from engine.search.novelty import NoveltyTracker

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "vulnerable.json"

SPACE = ActionSpace(
    usd="0x1000000000000000000000000000000000000001",
    col="0x2000000000000000000000000000000000000002",
    amm="0x3000000000000000000000000000000000000003",
    lending="0x4000000000000000000000000000000000000004",
)

BASELINE = EconState(
    attacker_usd=0,
    attacker_col=0,
    reserve_usd=1_000_000 * 10**18,
    reserve_col=1_000_000 * 10**18,
    oracle_price=10**18,
    reference_price=10**18,
    debt_usd=0,
    collateral_col=0,
)

CANDIDATE = Candidate(
    flash_token=SPACE.usd,
    flash_amount=50_000 * 10**18,
    actions=(Action(ActionType.SWAP_USD_FOR_COL, SPACE.amm, AmountRule.FIXED, 1),),
)

EXEC_RESULT = ExecResult(reverted=False, gas_used=200_000, tx_hash="0x1")


def _fitness(scenario=None) -> WeightedFitness:
    scenario = scenario or Scenario.load(SCENARIO_PATH)
    return WeightedFitness(scenario, SPACE, NoveltyTracker(BASELINE))


def test_price_deviation_signal_is_zero_at_reference_and_one_at_double():
    fitness = _fitness()
    assert fitness._price_deviation(BASELINE) == 0.0

    doubled = EconState(**{**BASELINE.__dict__, "oracle_price": 2 * 10**18})
    assert fitness._price_deviation(doubled) == 1.0


def test_capacity_per_capital_signal_matches_hand_computation():
    fitness = _fitness()
    state = EconState(**{**BASELINE.__dict__, "oracle_price": 2 * 10**18, "collateral_col": 100_000 * 10**18, "debt_usd": 50_000 * 10**18})

    # collateral_value = 100_000 * 2 = 200_000; max_debt = 75% of that = 150_000
    # capacity = 150_000 - 50_000 = 100_000; capital_deployed = flash_amount (USD) = 50_000
    assert fitness._capacity_per_capital(CANDIDATE, state) == pytest.approx(2.0)


def test_capacity_per_capital_is_zero_when_no_capital_deployed():
    fitness = _fitness()
    zero_flash = Candidate(flash_token=SPACE.usd, flash_amount=0, actions=())
    assert fitness._capacity_per_capital(zero_flash, BASELINE) == 0.0


def test_novelty_component_drops_to_zero_on_repeated_state():
    fitness = _fitness()
    first = fitness(CANDIDATE, BASELINE, EXEC_RESULT, _profit_usd=0, bad_debt_usd=0)
    second = fitness(CANDIDATE, BASELINE, EXEC_RESULT, _profit_usd=0, bad_debt_usd=0)
    # Same state seen twice -> novelty contributes on the first call only.
    assert first > second


def test_combined_weighted_sum_matches_hand_computation():
    scenario = Scenario.load(SCENARIO_PATH)
    fitness = _fitness(scenario)
    state = EconState(
        **{
            **BASELINE.__dict__,
            "oracle_price": 2 * 10**18,
            "collateral_col": 100_000 * 10**18,
            "debt_usd": 50_000 * 10**18,
            "attacker_usd": 20_000 * 10**18,  # raw captured USD, NOT net-of-capital profit
        }
    )

    # profit_usd param is Evaluator's net-of-initial-capital number — deliberately
    # NOT what the "profit" fitness signal uses (see fitness.py); pass something
    # implausible to prove the function really ignores it.
    score = fitness(CANDIDATE, state, EXEC_RESULT, _profit_usd=-999 * 10**18, bad_debt_usd=30_000 * 10**18)

    w = scenario.search.fitness_weights
    expected = (
        w.price_deviation * 1.0  # price doubled
        + w.capacity_per_capital * 2.0  # 100_000 capacity / 50_000 capital
        + w.bad_debt * 3.0  # 30_000 bad debt / 10_000 initial capital
        + w.profit * 2.0  # 20_000 raw captured USD / 10_000 initial capital
        + w.novelty * 1.0  # first sighting of this bucket
    )
    assert score == pytest.approx(expected)
