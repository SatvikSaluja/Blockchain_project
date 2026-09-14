"""Pure-Python evaluator tests — EconState/ExecResult are plain dataclasses,
so §7's four criteria can be exercised without a live Anvil at all."""

import math
from pathlib import Path

from engine.bridge import ExecResult
from engine.evaluator import Evaluator
from engine.observer import EconState
from engine.scenario import Scenario

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "vulnerable.json"
REFERENCE_PRICE = 10**18
GAS_USED = 100_000  # small, fixed, so it never dominates the USD-scale asserts below


def _state(**overrides) -> EconState:
    defaults = dict(
        attacker_usd=0,
        attacker_col=0,
        reserve_usd=1_000_000 * 10**18,
        reserve_col=1_000_000 * 10**18,
        oracle_price=REFERENCE_PRICE,
        reference_price=REFERENCE_PRICE,
        debt_usd=0,
        collateral_col=0,
    )
    defaults.update(overrides)
    return EconState(**defaults)


def _evaluator() -> Evaluator:
    return Evaluator(Scenario.load(SCENARIO_PATH))


def test_reverted_tx_is_not_exploit_and_scores_negative_infinity():
    ev = _evaluator().evaluate(
        ExecResult(reverted=True, gas_used=0, tx_hash=None), _state(attacker_usd=999_999 * 10**18)
    )
    assert ev.is_exploit is False
    assert ev.is_interesting is False
    assert ev.fitness == -math.inf
    assert ev.attacker_profit_usd == 0
    assert ev.protocol_bad_debt_usd == 0


def test_transient_capacity_increase_with_no_profit_or_bad_debt_is_not_exploit():
    # Below initial capital -> no profit; nothing borrowed -> no bad debt.
    state = _state(attacker_usd=5_000 * 10**18)
    ev = _evaluator().evaluate(ExecResult(reverted=False, gas_used=GAS_USED, tx_hash="0x1"), state)

    assert ev.is_exploit is False
    assert ev.is_interesting is True
    assert ev.protocol_bad_debt_usd == 0


def test_profit_with_no_protocol_bad_debt_is_not_the_target_class():
    # Attacker is up, but the loan is still fully backed at the true price.
    state = _state(attacker_usd=20_000 * 10**18, debt_usd=10_000 * 10**18, collateral_col=15_000 * 10**18)
    ev = _evaluator().evaluate(ExecResult(reverted=False, gas_used=GAS_USED, tx_hash="0x2"), state)

    assert ev.attacker_profit_usd > 0
    assert ev.protocol_bad_debt_usd == 0
    assert ev.is_exploit is False


def test_profitable_and_insolvent_is_a_qualifying_exploit():
    state = _state(attacker_usd=20_000 * 10**18, debt_usd=10_000 * 10**18, collateral_col=5_000 * 10**18)
    ev = _evaluator().evaluate(ExecResult(reverted=False, gas_used=GAS_USED, tx_hash="0x3"), state)

    assert ev.attacker_profit_usd > 0
    assert ev.protocol_bad_debt_usd == 5_000 * 10**18
    assert ev.is_exploit is True
    assert ev.is_interesting is False
    assert ev.violated_property == "debt_exceeds_collateral_at_reference_price"
    assert ev.fitness > 0
