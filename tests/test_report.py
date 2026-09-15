from pathlib import Path

import pytest
from web3 import Web3

from engine.bridge import ExecutionBridge
from engine.deploy import AnvilProcess, deploy_scenario
from engine.evaluator import Evaluator
from engine.observer import Observer
from engine.report import build_execution_trace, candidate_to_dict, render_report_md, symbol_for
from engine.scenario import Scenario
from tests.helpers import reference_exploit_candidate

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "vulnerable.json"


@pytest.fixture()
def rig():
    scenario = Scenario.load(SCENARIO_PATH)
    with AnvilProcess(port=8625) as anvil:
        w3 = Web3(Web3.HTTPProvider(anvil.rpc_url))
        dep = deploy_scenario(w3, scenario)
        bridge = ExecutionBridge(dep)
        observer = Observer(dep, scenario.evaluator.reference_price_usd)
        evaluator = Evaluator(scenario)
        yield bridge, observer, evaluator, dep, scenario


def test_symbol_for_resolves_known_addresses(rig):
    _, _, _, dep, _ = rig
    assert symbol_for(dep.usd.address, dep) == "USD"
    assert symbol_for(dep.col.address, dep) == "COL"
    assert symbol_for(dep.amm.address, dep) == "AMM"
    assert symbol_for(dep.lending.address, dep) == "LENDING"
    assert symbol_for("0xdeadbeef", dep) == "0xdeadbeef"  # unknown -> passthrough


def test_build_execution_trace_reconstructs_per_action_state(rig):
    bridge, observer, evaluator, dep, scenario = rig
    candidate = reference_exploit_candidate(dep)
    pre_state = observer.read()

    result = bridge.execute(candidate)
    assert not result.reverted
    post_state = observer.read()
    ev = evaluator.evaluate(candidate, result, post_state)
    assert ev.is_exploit

    trace = build_execution_trace(dep, result.tx_hash, pre_state, scenario.evaluator.reference_price_usd)

    assert len(trace) == len(candidate.actions)
    # Chained: each record's preState is the previous record's postState.
    assert trace[0].pre_state == pre_state
    for i in range(1, len(trace)):
        assert trace[i].pre_state == trace[i - 1].post_state
    # NOT trace[-1].post_state == post_state: the flash-loan repayment
    # happens *after* the last action's event fires, so the last record
    # reflects pre-repayment state — the observer's post-tx read (used by
    # Evaluator for the real profit/bad-debt numbers) is what's authoritative
    # for "what the attacker ended up with." Repayment only spends USD here.
    assert post_state.attacker_usd <= trace[-1].post_state.attacker_usd
    # Every record's action_type lines up with the candidate.
    assert [r.action_type for r in trace] == [a.action_type for a in candidate.actions]


def test_render_report_md_contains_required_sections(rig):
    bridge, observer, evaluator, dep, scenario = rig
    candidate = reference_exploit_candidate(dep)
    pre_state = observer.read()
    result = bridge.execute(candidate)
    post_state = observer.read()
    ev = evaluator.evaluate(candidate, result, post_state)
    trace = build_execution_trace(dep, result.tx_hash, pre_state, scenario.evaluator.reference_price_usd)

    report = render_report_md(candidate, dep, ev, trace, scenario, seed=1337, gas_used=result.gas_used)

    # SPEC §9: initial liquidity & lending params; minimized actions +
    # resolved amounts; before/after state; profit/bad-debt; violated
    # property; reproduction instructions.
    assert "AMM reserves" in report
    assert "Collateral factor" in report
    assert "SWAP_USD_FOR_COL" in report
    assert "resolved amount" in report
    assert "Attacker profit" in report
    assert "Protocol bad debt" in report
    assert ev.violated_property in report
    assert "forge test" in report
    assert "python -m engine.cli" in report


def test_candidate_to_dict_matches_attack_json_shape(rig):
    bridge, observer, evaluator, dep, scenario = rig
    candidate = reference_exploit_candidate(dep)
    result = bridge.execute(candidate)
    state = observer.read()
    ev = evaluator.evaluate(candidate, result, state)

    payload = candidate_to_dict(candidate, dep, ev, gas_used=result.gas_used, seed=1337, candidates_to_discovery=1)

    assert payload["flashToken"] == "USD"
    assert payload["actions"][0]["target"] == "AMM"
    assert payload["actions"][0]["type"] == "SWAP_USD_FOR_COL"
    assert payload["result"]["violatedProperty"] == ev.violated_property
    assert payload["result"]["seed"] == 1337
