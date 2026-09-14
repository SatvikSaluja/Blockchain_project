"""Action DSL for candidate attack sequences (SPEC §4).

`ActionType`/`AmountRule` mirror the Solidity enums in
contracts/AttackExecutor.sol *by ordinal position* — these values are
ABI-encoded as `uint8` and decoded on-chain via `ActionType(a.actionType)`,
so the Python and Solidity orderings must never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode

MAX_ACTIONS = 6

# Matches `enum ActionType` in contracts/AttackExecutor.sol.
class ActionType(IntEnum):
    SWAP_USD_FOR_COL = 0
    SWAP_COL_FOR_USD = 1
    DEPOSIT_COL = 2
    BORROW_USD = 3
    REPAY_USD = 4
    WITHDRAW_COL = 5


# Matches `enum AmountRule` in contracts/AttackExecutor.sol.
class AmountRule(IntEnum):
    FIXED = 0
    PCT_BALANCE = 1
    FRAC_RESERVES = 2
    PCT_BORROW_CAPACITY = 3


# ABI type for AttackExecutor.Action / Action[] (SPEC §5).
ACTION_TUPLE_ABI = "(uint8,address,uint8,uint256)"
ACTION_ARRAY_ABI = f"{ACTION_TUPLE_ABI}[]"


@dataclass(frozen=True)
class Action:
    action_type: ActionType
    target: str  # checksummed address
    amount_rule: AmountRule
    amount_param: int  # absolute (wei) or bps, per amount_rule

    def as_tuple(self) -> tuple[int, str, int, int]:
        """ABI-encodable tuple form: (uint8, address, uint8, uint256)."""
        return (int(self.action_type), self.target, int(self.amount_rule), self.amount_param)


@dataclass(frozen=True)
class Candidate:
    flash_token: str
    flash_amount: int
    actions: tuple[Action, ...]

    def __post_init__(self) -> None:
        if len(self.actions) > MAX_ACTIONS:
            raise ValueError(f"candidate has {len(self.actions)} actions, max is {MAX_ACTIONS}")

    def encode_actions(self) -> list[tuple[int, str, int, int]]:
        """Action[] in the shape web3.py expects for a tuple[] ABI param."""
        return [a.as_tuple() for a in self.actions]


def encode_actions_abi(candidate: Candidate) -> bytes:
    """Raw ABI encoding of the Action[] array (SPEC §5 encoding note)."""
    return abi_encode([ACTION_ARRAY_ABI], [candidate.encode_actions()])


def decode_actions_abi(data: bytes) -> list[tuple[int, str, int, int]]:
    """Inverse of encode_actions_abi — used to verify round-trip fidelity."""
    (decoded,) = abi_decode([ACTION_ARRAY_ABI], data)
    return list(decoded)
