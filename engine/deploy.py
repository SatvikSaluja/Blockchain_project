"""Persistent Anvil process + one-time contract deployment (SPEC §5 steps
1-3). The bridge (Phase 3 Task 14) snapshots/restores against this same
deployment for every candidate — contracts are never redeployed per-run.
"""

from __future__ import annotations

import atexit
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, NamedTuple

from web3 import Web3
from web3.contract import Contract

from engine.scenario import Scenario

REPO_ROOT = Path(__file__).resolve().parent.parent
FOUNDRY_OUT = REPO_ROOT / "out"

# Well-known deterministic Foundry/Anvil test mnemonic — fixed per SPEC §1
# ("every run is seeded... Anvil is launched with a fixed mnemonic").
FIXED_MNEMONIC = "test test test test test test test test test test test junk"
DEFAULT_PORT = 8545


class AnvilProcess:
    """Owns the `anvil` OS process. Auto-mining stays on (the default) so
    every submitted tx lands in its own block deterministically — this is
    NOT the intra-candidate snapshot/restore mechanism (see engine/bridge.py)."""

    def __init__(self, port: int = DEFAULT_PORT, mnemonic: str = FIXED_MNEMONIC):
        if shutil.which("anvil") is None:
            raise RuntimeError("anvil not found on PATH — install Foundry (foundryup)")
        self.port = port
        self.mnemonic = mnemonic
        self._proc: subprocess.Popen | None = None

    @property
    def rpc_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self._proc = subprocess.Popen(
            ["anvil", "--port", str(self.port), "--mnemonic", self.mnemonic, "--silent"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        atexit.register(self.stop)
        self._wait_ready()

    def _wait_ready(self, timeout: float = 10.0) -> None:
        w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError("anvil exited immediately on startup")
            try:
                if w3.is_connected():
                    return
            except Exception:
                pass
            time.sleep(0.1)
        raise RuntimeError("anvil did not become ready in time")

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def __enter__(self) -> "AnvilProcess":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def _load_artifact(contract_name: str) -> dict:
    """out/<Contract>.sol/<Contract>.json — every contract here lives in a
    file named after itself, so name doubles as both path segments."""
    path = FOUNDRY_OUT / f"{contract_name}.sol" / f"{contract_name}.json"
    return json.loads(path.read_text())


def _deploy(w3: Web3, name: str, *args: Any, from_account: str | None = None) -> Contract:
    artifact = _load_artifact(name)
    factory = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"]["object"])
    tx_hash = factory.constructor(*args).transact({"from": from_account or w3.eth.default_account})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return w3.eth.contract(address=receipt.contractAddress, abi=artifact["abi"])


def _send(w3: Web3, fn: Any, from_account: str) -> None:
    tx_hash = fn.transact({"from": from_account})
    w3.eth.wait_for_transaction_receipt(tx_hash)


class Deployment(NamedTuple):
    w3: Web3
    usd: Contract
    col: Contract
    amm: Contract
    oracle: Contract
    lending: Contract
    flash_lender: Contract
    executor: Contract
    deployer: str  # also the AMM/lending liquidity provider
    attacker: str  # owns AttackExecutor; calls executeAttack


def deploy_scenario(w3: Web3, scenario: Scenario) -> Deployment:
    """Deploy order per SPEC §3: USD -> COL -> AMM -> Oracle(AMM) ->
    LendingMarket -> FlashLender -> AttackExecutor, then seed liquidity /
    lending reserves / attacker capital from `scenario`."""
    deployer, attacker = w3.eth.accounts[0], w3.eth.accounts[1]
    w3.eth.default_account = deployer

    usd = _deploy(w3, "MockToken", "USD Coin", "USD")
    col = _deploy(w3, "MockToken", "Collateral", "COL")
    amm = _deploy(w3, "ConstantProductAMM", usd.address, col.address, scenario.amm.fee_bps)
    oracle = _deploy(w3, "SpotOracle", amm.address)
    lending = _deploy(
        w3, "LendingMarket", oracle.address, usd.address, col.address, scenario.lending.collateral_factor_bps
    )
    flash_lender = _deploy(w3, "FlashLender", usd.address, col.address, scenario.flash.fee_bps)
    executor = _deploy(
        w3,
        "AttackExecutor",
        amm.address,
        "0x0000000000000000000000000000000000000000",  # amm2: no second pool in any current scenario
        oracle.address,
        lending.address,
        flash_lender.address,
        usd.address,
        col.address,
        from_account=attacker,
    )

    # Seed AMM liquidity.
    _send(w3, usd.functions.mint(deployer, scenario.amm.reserve_usd), deployer)
    _send(w3, col.functions.mint(deployer, scenario.amm.reserve_col), deployer)
    _send(w3, usd.functions.approve(amm.address, scenario.amm.reserve_usd), deployer)
    _send(w3, col.functions.approve(amm.address, scenario.amm.reserve_col), deployer)
    _send(w3, amm.functions.addLiquidity(scenario.amm.reserve_usd, scenario.amm.reserve_col), deployer)

    # Seed lending-market USD reserves.
    _send(w3, usd.functions.mint(deployer, scenario.lending.usd_liquidity), deployer)
    _send(w3, usd.functions.approve(lending.address, scenario.lending.usd_liquidity), deployer)
    _send(w3, lending.functions.seedLiquidity(scenario.lending.usd_liquidity), deployer)

    # Flash-loan liquidity, generous headroom above AMM reserves so
    # candidates can flash-borrow up to the full pool size (matches the
    # Foundry Fixture).
    _send(w3, usd.functions.mint(flash_lender.address, 2 * scenario.amm.reserve_usd), deployer)
    _send(w3, col.functions.mint(flash_lender.address, 2 * scenario.amm.reserve_col), deployer)

    # Modeled attacker starting capital — evaluator-side accounting baseline
    # (SPEC §7 deducts it from profit); not consumed by the MVP flash-loan-
    # only exploit itself.
    _send(w3, usd.functions.mint(attacker, scenario.attacker.initial_capital_usd), deployer)

    return Deployment(w3, usd, col, amm, oracle, lending, flash_lender, executor, deployer, attacker)
