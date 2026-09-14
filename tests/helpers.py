"""Shared test helpers (no test_ prefix — pytest won't collect this file)."""

from engine.actions import Action, ActionType, AmountRule, Candidate
from engine.deploy import Deployment

# Mirrors test/ManualExploit.t.sol exactly (SPEC §4 reference exploit) so
# Python and Solidity numbers can be compared directly (Task 17).
REFERENCE_FLASH_AMOUNT = 400_000 * 10**18


def reference_exploit_candidate(dep: Deployment, flash_amount: int = REFERENCE_FLASH_AMOUNT) -> Candidate:
    """Flash-borrow USD, swap 100% into COL to inflate the oracle, deposit
    all of it as collateral, borrow to 100% of the (inflated) capacity, then
    a no-op unwind (no COL left to swap back — matches the Solidity test)."""
    return Candidate(
        flash_token=dep.usd.address,
        flash_amount=flash_amount,
        actions=(
            Action(ActionType.SWAP_USD_FOR_COL, dep.amm.address, AmountRule.PCT_BALANCE, 10_000),
            Action(ActionType.DEPOSIT_COL, dep.lending.address, AmountRule.PCT_BALANCE, 10_000),
            Action(ActionType.BORROW_USD, dep.lending.address, AmountRule.PCT_BORROW_CAPACITY, 10_000),
            Action(ActionType.SWAP_COL_FOR_USD, dep.amm.address, AmountRule.PCT_BALANCE, 10_000),
        ),
    )
