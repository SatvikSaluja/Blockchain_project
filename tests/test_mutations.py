import random

from engine.actions import MAX_ACTIONS, ActionType, AmountRule, Candidate
from engine.search.mutations import MUTATIONS, ActionSpace, mutate, random_candidate

SPACE = ActionSpace(
    usd="0x1000000000000000000000000000000000000001",
    col="0x2000000000000000000000000000000000000002",
    amm="0x3000000000000000000000000000000000000003",
    lending="0x4000000000000000000000000000000000000004",
)


def _assert_well_formed(c: Candidate) -> None:
    assert isinstance(c, Candidate)
    assert len(c.actions) <= MAX_ACTIONS
    assert c.flash_token in SPACE.tokens
    assert c.flash_amount >= 0
    for a in c.actions:
        assert isinstance(a.action_type, ActionType)
        assert isinstance(a.amount_rule, AmountRule)
        assert a.target in (SPACE.amm, SPACE.lending)
        assert a.amount_param >= 0
        # target must match the action type's expected contract, exactly
        # what AttackExecutor's on-chain `require` checks.
        assert a.target == SPACE.target_for(a.action_type)


def test_random_candidates_are_always_well_formed():
    rng = random.Random(1337)
    for _ in range(1000):
        _assert_well_formed(random_candidate(SPACE, rng))


def test_all_mutations_always_produce_well_formed_candidates():
    rng = random.Random(2024)
    c = random_candidate(SPACE, rng)
    for _ in range(2000):
        op = rng.choice(MUTATIONS)
        c = op(c, rng, SPACE)
        _assert_well_formed(c)


def test_mutate_picks_among_all_operators_uses_weighted_rng():
    rng = random.Random(7)
    c = random_candidate(SPACE, rng)
    for _ in range(500):
        c = mutate(c, rng, SPACE)
        _assert_well_formed(c)


def test_insert_action_never_exceeds_max_actions():
    rng = random.Random(3)
    # Build a candidate already at the cap and confirm insert is a no-op.
    full = random_candidate(SPACE, rng, max_actions=MAX_ACTIONS)
    while len(full.actions) < MAX_ACTIONS:
        full = random_candidate(SPACE, rng, max_actions=MAX_ACTIONS)
    from engine.search.mutations import insert_action

    result = insert_action(full, rng, SPACE)
    assert len(result.actions) == MAX_ACTIONS
