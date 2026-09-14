from pathlib import Path

import pytest
from web3 import Web3

from engine.deploy import AnvilProcess, deploy_scenario
from engine.scenario import Scenario

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "vulnerable.json"


@pytest.fixture(scope="module")
def deployment():
    scenario = Scenario.load(SCENARIO_PATH)
    with AnvilProcess(port=8555) as anvil:
        w3 = Web3(Web3.HTTPProvider(anvil.rpc_url))
        yield deploy_scenario(w3, scenario), scenario


def test_amm_reserves_match_scenario(deployment):
    dep, scenario = deployment
    r_usd, r_col = dep.amm.functions.getReserves().call()
    assert r_usd == scenario.amm.reserve_usd
    assert r_col == scenario.amm.reserve_col


def test_lending_liquidity_and_params_match_scenario(deployment):
    dep, scenario = deployment
    assert dep.usd.functions.balanceOf(dep.lending.address).call() == scenario.lending.usd_liquidity
    assert dep.lending.functions.collateralFactorBps().call() == scenario.lending.collateral_factor_bps


def test_attacker_funded_with_initial_capital(deployment):
    dep, scenario = deployment
    assert dep.usd.functions.balanceOf(dep.attacker).call() == scenario.attacker.initial_capital_usd


def test_executor_owner_is_attacker(deployment):
    dep, _ = deployment
    assert dep.executor.functions.owner().call() == dep.attacker


def test_oracle_reads_spot_price(deployment):
    dep, _ = deployment
    assert dep.oracle.functions.price().call() == 10**18  # equal reserves -> price 1.0
