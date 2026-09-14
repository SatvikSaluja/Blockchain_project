"""Phase 4 checkpoint (SPEC §11): random search must rediscover a qualifying
exploit within budget on the vulnerable scenario — without ever being told
the Phase-2 reference sequence (SPEC §14: no hardcoded winning sequence in
the search path; mutations.py/random_search.py know nothing about it).

Marked `discovery` (slow/integration, excluded from the fast default suite):

    pytest -m "not discovery"   # fast suite
    pytest -m discovery         # just this
    pytest                      # everything
"""

import random
from pathlib import Path

import pytest
from web3 import Web3

from engine.bridge import ExecutionBridge
from engine.deploy import AnvilProcess, deploy_scenario
from engine.evaluator import Evaluator
from engine.observer import Observer
from engine.scenario import Scenario
from engine.search.mutations import ActionSpace
from engine.search.random_search import run_random_search

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "vulnerable.json"

# Generous relative to the ~165 candidates it empirically takes at seed 1337
# (500-candidate CLI smoke run), tiny relative to scenario.json's default
# 50,000 budget — keeps this test in the tens-of-seconds range.
DISCOVERY_BUDGET = 2_000


@pytest.mark.discovery
def test_random_search_rediscovers_a_qualifying_exploit():
    scenario = Scenario.load(SCENARIO_PATH)
    rng = random.Random(scenario.seed)

    with AnvilProcess(port=8605) as anvil:
        w3 = Web3(Web3.HTTPProvider(anvil.rpc_url))
        deployment = deploy_scenario(w3, scenario)
        bridge = ExecutionBridge(deployment)
        observer = Observer(deployment, scenario.evaluator.reference_price_usd)
        evaluator = Evaluator(scenario)
        space = ActionSpace(
            usd=deployment.usd.address,
            col=deployment.col.address,
            amm=deployment.amm.address,
            lending=deployment.lending.address,
        )

        result = run_random_search(bridge, evaluator, observer, space, rng, DISCOVERY_BUDGET)

    assert result.candidates_to_first_exploit is not None, (
        f"random search found no qualifying exploit in {DISCOVERY_BUDGET} candidates"
    )
    assert result.candidates_to_first_exploit <= DISCOVERY_BUDGET
    assert len(result.exploits) >= 1

    _, first_evaluation, _ = result.exploits[0]
    assert first_evaluation.is_exploit is True
    assert first_evaluation.attacker_profit_usd > 0
    assert first_evaluation.protocol_bad_debt_usd > 0
    assert first_evaluation.violated_property == "debt_exceeds_collateral_at_reference_price"
