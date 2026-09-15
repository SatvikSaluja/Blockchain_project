"""Generates from the Phase-2 reference candidate and runs `forge test` on
the result — the only way to actually verify generated Solidity compiles
and passes, not just that string templating didn't crash."""

import os
import subprocess
from pathlib import Path

import pytest
from web3 import Web3

from engine.deploy import AnvilProcess, deploy_scenario
from engine.scenario import Scenario
from engine.solgen import generate_reproducer_sol
from tests.helpers import reference_exploit_candidate

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "vulnerable.json"
GENERATED_DIR = REPO_ROOT / "test" / "generated"

# An obviously-synthetic seed for this test's OWN generated filename — never
# scenario.seed (1337). test/generated/ also holds real, committed run
# artifacts (e.g. ExploitReproducer_1337.t.sol from a genuine CLI run); this
# test creates-then-deletes a file, and must never collide with one of those
# or its cleanup silently deletes a real committed artifact (this happened).
TEST_ONLY_SEED = 999_999_999

pytestmark = pytest.mark.discovery  # shells out to forge test; slow-ish, needs live Anvil for the Python half


def test_generated_reproducer_compiles_and_passes():
    scenario = Scenario.load(SCENARIO_PATH)
    with AnvilProcess(port=8635) as anvil:
        w3 = Web3(Web3.HTTPProvider(anvil.rpc_url))
        dep = deploy_scenario(w3, scenario)
        candidate = reference_exploit_candidate(dep)
        source = generate_reproducer_sol(candidate, dep, seed=TEST_ONLY_SEED)

    out_path = GENERATED_DIR / f"ExploitReproducer_{TEST_ONLY_SEED}.t.sol"
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(source)
    try:
        result = subprocess.run(
            ["forge", "test", "--match-contract", f"ExploitReproducer_{TEST_ONLY_SEED}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=os.environ,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "[PASS]" in result.stdout
    finally:
        out_path.unlink(missing_ok=True)
