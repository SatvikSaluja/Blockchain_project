from pathlib import Path

from engine.scenario import Scenario, parse_wei

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_parse_wei_handles_exponent_strings_and_ints():
    assert parse_wei("1000000e18") == 1_000_000 * 10**18
    assert parse_wei("1e18") == 10**18
    assert parse_wei("42") == 42
    assert parse_wei(42) == 42


def test_loads_vulnerable_scenario():
    scenario = Scenario.load(REPO_ROOT / "scenarios" / "vulnerable.json")

    assert scenario.seed == 1337
    assert scenario.amm.reserve_usd == 1_000_000 * 10**18
    assert scenario.amm.reserve_col == 1_000_000 * 10**18
    assert scenario.amm.fee_bps == 0
    assert scenario.lending.usd_liquidity == 500_000 * 10**18
    assert scenario.lending.collateral_factor_bps == 7500
    assert scenario.flash.fee_bps == 9
    assert scenario.attacker.initial_capital_usd == 10_000 * 10**18
    assert scenario.evaluator.reference_price_usd == 10**18
    assert scenario.gas.gas_price_gwei == 20
    assert scenario.gas.eth_price_usd == 3_000 * 10**18
    assert scenario.search.max_actions == 6
    assert scenario.search.budget_candidates == 50_000
    assert scenario.search.fitness_weights.bad_debt == 2.0
    assert scenario.search.selection_epsilon == 0.1
