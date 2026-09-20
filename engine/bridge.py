"""Execution bridge (SPEC §5): submits one tx per candidate against the
persistent Anvil deployment, then restores state via snapshot/revert.
Contracts are deployed exactly once per run — never redeployed per candidate.
"""

from __future__ import annotations

from dataclasses import dataclass

from web3 import Web3

from engine.actions import Candidate
from engine.deploy import Deployment


@dataclass(frozen=True)
class ExecResult:
    reverted: bool
    gas_used: int
    tx_hash: str | None
    revert_reason: str | None = None


class StateGuard:
    """The only code path allowed to call evm_revert. Anvil's evm_revert
    CONSUMES the snapshot and invalidates every snapshot taken after it
    (SPEC §5 gotcha) — this wrapper makes "revert, then immediately
    re-snapshot" structurally impossible to get wrong: there is no method
    that reverts without also leaving a fresh snapshot in place.
    """

    def __init__(self, w3: Web3):
        self._w3 = w3
        self._snapshot_id: str | None = None

    def snapshot(self) -> None:
        self._snapshot_id = self._w3.manager.request_blocking("evm_snapshot", [])

    def restore(self) -> None:
        if self._snapshot_id is None:
            raise RuntimeError("StateGuard.restore() called before any snapshot() was taken")
        ok = self._w3.manager.request_blocking("evm_revert", [self._snapshot_id])
        if not ok:
            raise RuntimeError(f"evm_revert failed for snapshot {self._snapshot_id}")
        self.snapshot()  # re-snapshot immediately — never skip this


class ExecutionBridge:
    def __init__(self, deployment: Deployment):
        self.deployment = deployment
        self.w3 = deployment.w3
        self._guard = StateGuard(self.w3)
        self._guard.snapshot()  # baseline, right after deployment

    def snapshot(self) -> None:
        self._guard.snapshot()

    def restore(self) -> None:
        self._guard.restore()

    def execute(self, candidate: Candidate) -> ExecResult:
        """Submit exactly one `executeAttack` tx. A revert (whether raised
        before mining or mined with status 0) means "invalid candidate" —
        the caller decides what to do with that, this method never raises
        for an ordinary contract revert."""
        executor = self.deployment.executor
        fn = executor.functions.executeAttack(
            candidate.flash_token, candidate.flash_amount, candidate.encode_actions()
        )
        try:
            tx_hash = fn.transact({"from": self.deployment.attacker})
        except Exception as exc:  # node rejected before mining (e.g. eth_call pre-check)
            return ExecResult(reverted=True, gas_used=0, tx_hash=None, revert_reason=str(exc))

        # web3's default wait is 120s — far too generous for a local
        # auto-mining Anvil (a healthy receipt returns in well under a
        # second) and, per a real overnight benchmark run, too slow to
        # notice a wedged node quickly: it hung here after ~10 hours of
        # sustained snapshot/revert load with nothing checkpointed since.
        # This still raises (not swallowed) rather than being folded into
        # ExecResult.reverted — an infra hang is not "an invalid candidate"
        # and treating it as one would make a dead node look like a search
        # loop quietly grinding through reverts forever. Callers that need
        # to survive this (experiments/benchmark.py's multi-hour sweep)
        # catch it at their own natural retry boundary.
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        if receipt.status == 0:
            return ExecResult(reverted=True, gas_used=receipt.gasUsed, tx_hash=tx_hash.hex())
        return ExecResult(reverted=False, gas_used=receipt.gasUsed, tx_hash=tx_hash.hex())
