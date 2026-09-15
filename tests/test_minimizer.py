from pathlib import Path

import pytest
from web3 import Web3

from engine.actions import Action, ActionType, AmountRule, Candidate
from engine.bridge import ExecutionBridge
from engine.deploy import AnvilProcess, deploy_scenario
from engine.evaluator import Evaluator
from engine.minimizer import minimize
from engine.observer import Observer
from engine.scenario import Scenario
from tests.helpers import reference_exploit_candidate

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "vulnerable.json"

pytestmark = pytest.mark.discovery  # slow: binary-search shrink is ~90 EVM
# calls just for flash_amount; keep out of the fast default suite.


@pytest.fixture()
def rig():
    scenario = Scenario.load(SCENARIO_PATH)
    with AnvilProcess(port=8615) as anvil:
        w3 = Web3(Web3.HTTPProvider(anvil.rpc_url))
        dep = deploy_scenario(w3, scenario)
        yield ExecutionBridge(dep), Evaluator(scenario), Observer(dep, scenario.evaluator.reference_price_usd), dep


def test_minimizer_strips_padding_and_shrinks_to_reference_shape(rig):
    bridge, evaluator, observer, dep = rig
    core = reference_exploit_candidate(dep)

    # Pad with two guaranteed no-op actions (FIXED amount 0 always resolves
    # to a no-op) that shouldn't affect qualification either way.
    padded = Candidate(
        flash_token=core.flash_token,
        flash_amount=core.flash_amount,
        actions=(Action(ActionType.WITHDRAW_COL, dep.lending.address, AmountRule.FIXED, 0),)
        + core.actions
        + (Action(ActionType.REPAY_USD, dep.lending.address, AmountRule.FIXED, 0),),
    )

    # Sanity: the padded 6-action candidate still qualifies before minimizing.
    result = bridge.execute(padded)
    assert not result.reverted
    state = observer.read()
    ev = evaluator.evaluate(padded, result, state)
    bridge.restore()
    assert ev.is_exploit

    minimized = minimize(bridge, evaluator, observer, padded)

    # Padding stripped, AND core.actions[3] (the unwind swap) is itself a
    # no-op here — 100% of the COL was already deposited, so there's
    # nothing left to swap back (see tests/helpers.py) — so the minimizer
    # correctly strips that too, reaching the true 3-action minimum.
    assert [a.action_type for a in minimized.actions] == [a.action_type for a in core.actions[:3]]
    assert len(minimized.actions) == 3

    # Amounts shrunk to <= the original (never grown).
    for shrunk, original in zip(minimized.actions, core.actions[:3]):
        assert shrunk.amount_param <= original.amount_param
    assert minimized.flash_amount <= core.flash_amount

    # The minimized candidate is itself still a genuine, replayable exploit
    # (minimization must never produce a candidate that stops qualifying).
    result = bridge.execute(minimized)
    assert not result.reverted
    state = observer.read()
    final_ev = evaluator.evaluate(minimized, result, state)
    bridge.restore()
    assert final_ev.is_exploit


def test_minimizer_is_a_no_op_on_an_already_minimal_candidate(rig):
    bridge, evaluator, observer, dep = rig
    core = reference_exploit_candidate(dep)

    once = minimize(bridge, evaluator, observer, core)
    twice = minimize(bridge, evaluator, observer, once)

    # Fixed point: minimizing an already-minimized candidate changes nothing.
    assert once == twice
