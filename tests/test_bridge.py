from pathlib import Path

import pytest
from web3 import Web3

from engine.actions import Action, ActionType, AmountRule, Candidate
from engine.bridge import ExecutionBridge
from engine.deploy import AnvilProcess, deploy_scenario
from engine.scenario import Scenario
from tests.helpers import reference_exploit_candidate

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "vulnerable.json"
BAD_TARGET = "0x" + "12" * 20  # well-formed but wrong address


@pytest.fixture()
def bridge():
    scenario = Scenario.load(SCENARIO_PATH)
    with AnvilProcess(port=8575) as anvil:
        w3 = Web3(Web3.HTTPProvider(anvil.rpc_url))
        dep = deploy_scenario(w3, scenario)
        yield ExecutionBridge(dep), dep


def test_valid_candidate_executes_and_changes_state(bridge):
    eb, dep = bridge
    baseline_reserves = dep.amm.functions.getReserves().call()

    result = eb.execute(reference_exploit_candidate(dep))

    assert not result.reverted
    assert result.gas_used > 0
    assert dep.amm.functions.getReserves().call() != baseline_reserves
    assert dep.lending.functions.debtOf(dep.executor.address).call() > 0


def test_invalid_candidate_reports_reverted_without_raising(bridge):
    eb, dep = bridge
    # DEPOSIT_COL with a bad target ("AttackExecutor: bad target") is a
    # cheap deliberate revert (mirrors AttackExecutorTest.test_revertsOnBadTarget).
    bad = Candidate(
        flash_token=dep.usd.address,
        flash_amount=1_000 * 10**18,
        actions=(Action(ActionType.DEPOSIT_COL, BAD_TARGET, AmountRule.FIXED, 1),),
    )
    result = eb.execute(bad)
    assert result.reverted


def test_restore_reverts_state_byte_for_byte(bridge):
    eb, dep = bridge
    baseline_reserves = dep.amm.functions.getReserves().call()
    baseline_attacker_usd = dep.usd.functions.balanceOf(dep.attacker).call()
    baseline_debt = dep.lending.functions.debtOf(dep.executor.address).call()

    result = eb.execute(reference_exploit_candidate(dep))
    assert not result.reverted
    assert dep.amm.functions.getReserves().call() != baseline_reserves  # sanity: state did move

    eb.restore()

    assert dep.amm.functions.getReserves().call() == baseline_reserves
    assert dep.usd.functions.balanceOf(dep.attacker).call() == baseline_attacker_usd
    assert dep.lending.functions.debtOf(dep.executor.address).call() == baseline_debt


def test_revert_then_execute_again_still_works(bridge):
    """Exercises the snapshot-consumption gotcha (SPEC §5): a revert+restore
    cycle must leave a fresh, usable snapshot for the next candidate."""
    eb, dep = bridge
    bad = Candidate(
        flash_token=dep.usd.address,
        flash_amount=1_000 * 10**18,
        actions=(Action(ActionType.DEPOSIT_COL, BAD_TARGET, AmountRule.FIXED, 1),),
    )
    r1 = eb.execute(bad)
    assert r1.reverted
    eb.restore()

    r2 = eb.execute(reference_exploit_candidate(dep))
    assert not r2.reverted
    eb.restore()

    r3 = eb.execute(reference_exploit_candidate(dep))
    assert not r3.reverted
