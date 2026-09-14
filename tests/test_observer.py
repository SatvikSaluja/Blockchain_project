from pathlib import Path

import pytest
from web3 import Web3

from engine.bridge import ExecutionBridge
from engine.deploy import AnvilProcess, deploy_scenario
from engine.observer import Observer
from engine.scenario import Scenario
from tests.helpers import reference_exploit_candidate

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "vulnerable.json"


@pytest.fixture()
def rig():
    scenario = Scenario.load(SCENARIO_PATH)
    with AnvilProcess(port=8585) as anvil:
        w3 = Web3(Web3.HTTPProvider(anvil.rpc_url))
        dep = deploy_scenario(w3, scenario)
        yield ExecutionBridge(dep), Observer(dep, scenario.evaluator.reference_price_usd), scenario


def test_baseline_state_matches_seeded_scenario(rig):
    _, observer, scenario = rig
    state = observer.read()

    assert state.reserve_usd == scenario.amm.reserve_usd
    assert state.reserve_col == scenario.amm.reserve_col
    assert state.oracle_price == 10**18
    assert state.reference_price == scenario.evaluator.reference_price_usd
    assert state.attacker_usd == 0
    assert state.attacker_col == 0
    assert state.debt_usd == 0
    assert state.collateral_col == 0


def test_state_reflects_exploit_execution(rig):
    bridge, observer, _ = rig
    dep = bridge.deployment

    result = bridge.execute(reference_exploit_candidate(dep))
    assert not result.reverted

    state = observer.read()

    assert state.oracle_price > state.reference_price  # oracle manipulated above truth
    assert state.debt_usd > 0
    assert state.collateral_col > 0
    assert state.attacker_usd > 0  # exploit left profit sitting in the executor
    assert state.attacker_col == 0  # 100% of COL was deposited as collateral


def test_to_json_uses_execution_trace_camel_case_shape(rig):
    _, observer, _ = rig
    payload = observer.read().to_json()

    assert set(payload.keys()) == {
        "attackerUsd",
        "attackerCol",
        "reserveUsd",
        "reserveCol",
        "oraclePrice",
        "referencePrice",
        "debtUsd",
        "collateralCol",
    }
