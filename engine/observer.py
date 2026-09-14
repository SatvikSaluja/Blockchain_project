"""Reads economic state via view calls (SPEC §6.4 signals, §9
execution_trace.json shape). Never touches the contracts' own oracle for
judgment — that's the Evaluator's job (§7); the observer just reports what's
actually on-chain, manipulated oracle included.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.deploy import Deployment


@dataclass(frozen=True)
class EconState:
    attacker_usd: int
    attacker_col: int
    reserve_usd: int
    reserve_col: int
    oracle_price: int
    reference_price: int
    debt_usd: int
    collateral_col: int

    def to_json(self) -> dict:
        """camelCase shape matching SPEC Appendix execution_trace.json."""
        return {
            "attackerUsd": self.attacker_usd,
            "attackerCol": self.attacker_col,
            "reserveUsd": self.reserve_usd,
            "reserveCol": self.reserve_col,
            "oraclePrice": self.oracle_price,
            "referencePrice": self.reference_price,
            "debtUsd": self.debt_usd,
            "collateralCol": self.collateral_col,
        }


class Observer:
    """`attackerUsd`/`attackerCol` read AttackExecutor's own balance, not the
    EOA's — that's where a flash-loan-only attack's residual profit actually
    sits. The EOA's `initialCapitalUsd` is a separate evaluator-side
    accounting baseline (§7), not summed in here."""

    def __init__(self, deployment: Deployment, reference_price: int):
        self.deployment = deployment
        self.reference_price = reference_price

    def read(self) -> EconState:
        dep = self.deployment
        executor_addr = dep.executor.address
        r_usd, r_col = dep.amm.functions.getReserves().call()
        return EconState(
            attacker_usd=dep.usd.functions.balanceOf(executor_addr).call(),
            attacker_col=dep.col.functions.balanceOf(executor_addr).call(),
            reserve_usd=r_usd,
            reserve_col=r_col,
            oracle_price=dep.oracle.functions.price().call(),
            reference_price=self.reference_price,
            debt_usd=dep.lending.functions.debtOf(executor_addr).call(),
            collateral_col=dep.lending.functions.collateralOf(executor_addr).call(),
        )
