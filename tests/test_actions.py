from engine.actions import (
    Action,
    ActionType,
    AmountRule,
    Candidate,
    decode_actions_abi,
    encode_actions_abi,
)

ZERO = "0x0000000000000000000000000000000000000000"
AMM = "0x1000000000000000000000000000000000000001"
LENDING = "0x2000000000000000000000000000000000000002"


def test_enum_ordinals_match_solidity():
    # contracts/AttackExecutor.sol enum ActionType / AmountRule order.
    assert [t.value for t in ActionType] == [0, 1, 2, 3, 4, 5]
    assert ActionType.SWAP_USD_FOR_COL == 0
    assert ActionType.WITHDRAW_COL == 5
    assert [r.value for r in AmountRule] == [0, 1, 2, 3]
    assert AmountRule.PCT_BORROW_CAPACITY == 3


def test_candidate_rejects_too_many_actions():
    actions = tuple(
        Action(ActionType.DEPOSIT_COL, LENDING, AmountRule.FIXED, 1) for _ in range(7)
    )
    try:
        Candidate(flash_token=ZERO, flash_amount=1, actions=actions)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_candidate_and_action_are_hashable_and_dedupe():
    c1 = Candidate(
        flash_token=ZERO,
        flash_amount=100,
        actions=(Action(ActionType.SWAP_USD_FOR_COL, AMM, AmountRule.FIXED, 10),),
    )
    c2 = Candidate(
        flash_token=ZERO,
        flash_amount=100,
        actions=(Action(ActionType.SWAP_USD_FOR_COL, AMM, AmountRule.FIXED, 10),),
    )
    assert c1 == c2
    assert hash(c1) == hash(c2)
    assert len({c1, c2}) == 1


def test_encode_decode_actions_round_trips():
    candidate = Candidate(
        flash_token=ZERO,
        flash_amount=250_000 * 10**18,
        actions=(
            Action(ActionType.SWAP_USD_FOR_COL, AMM, AmountRule.FRAC_RESERVES, 4000),
            Action(ActionType.DEPOSIT_COL, LENDING, AmountRule.PCT_BALANCE, 10_000),
            Action(ActionType.BORROW_USD, LENDING, AmountRule.PCT_BORROW_CAPACITY, 10_000),
            Action(ActionType.SWAP_COL_FOR_USD, AMM, AmountRule.PCT_BALANCE, 10_000),
        ),
    )

    encoded = encode_actions_abi(candidate)
    decoded = decode_actions_abi(encoded)

    assert len(decoded) == len(candidate.actions)
    for (actionType, target, amountRule, amountParam), action in zip(decoded, candidate.actions):
        assert actionType == int(action.action_type)
        assert target.lower() == action.target.lower()
        assert amountRule == int(action.amount_rule)
        assert amountParam == action.amount_param
