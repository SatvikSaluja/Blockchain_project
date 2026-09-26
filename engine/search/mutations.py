"""Random candidate generation + mutation operators (SPEC §6.2).

Every function here is *total*: given any well-formed `Candidate` (and the
`ActionSpace` describing which addresses are legal `target`/`flash_token`
values for one deployment) it always returns another well-formed
`Candidate`. Whether that candidate is economically valid is decided by
execution (engine/bridge.py), never by the mutator.
"""

from __future__ import annotations

import dataclasses
import random

from engine.actions import MAX_ACTIONS, Action, ActionType, AmountRule, Candidate

# Generous ceiling for FIXED amounts / flash size — AttackExecutor clamps
# every resolved amount to available balance/capacity anyway (SPEC §3.6), so
# this only needs to be "large enough to matter," not scenario-exact.
MAX_FIXED_AMOUNT = 10_000_000 * 10**18
BPS_MAX = 10_000

# NOTE (fairness, 2026-09-26): an earlier version gave guided search's
# mutation operators a "boundary bias" that snapped amounts to 0%/100% (and
# favored the MAX end 85% of the time). That is a confound for the §12
# guided-vs-random comparison: near-100% amounts are exactly the shape of
# the known reference exploit, so it was a hint pointing at the answer, not
# generic exploration. Removed so the *only* thing separating guided from
# random is fitness-weighted selection + corpus retention — the actual claim
# under test. `havoc` (multi-mutation step) stays: it widens step SIZE, it
# does not steer toward any particular answer shape.

# Each swap/deposit-withdraw/borrow-repay pair shares one target contract, so
# flipping within a pair never needs a different `target`.
_OPPOSITE = {
    ActionType.SWAP_USD_FOR_COL: ActionType.SWAP_COL_FOR_USD,
    ActionType.SWAP_COL_FOR_USD: ActionType.SWAP_USD_FOR_COL,
    ActionType.DEPOSIT_COL: ActionType.WITHDRAW_COL,
    ActionType.WITHDRAW_COL: ActionType.DEPOSIT_COL,
    ActionType.BORROW_USD: ActionType.REPAY_USD,
    ActionType.REPAY_USD: ActionType.BORROW_USD,
}


@dataclasses.dataclass(frozen=True)
class ActionSpace:
    """The addresses a candidate's `target`/`flash_token` fields may
    reference — bound to one deployment."""

    usd: str
    col: str
    amm: str
    lending: str

    def target_for(self, action_type: ActionType) -> str:
        if action_type in (ActionType.SWAP_USD_FOR_COL, ActionType.SWAP_COL_FOR_USD):
            return self.amm
        return self.lending

    @property
    def tokens(self) -> tuple[str, str]:
        return (self.usd, self.col)


def _random_amount_param(rule: AmountRule, rng: random.Random) -> int:
    if rule == AmountRule.FIXED:
        return rng.randint(0, MAX_FIXED_AMOUNT)
    return rng.randint(1, BPS_MAX)


def random_action(space: ActionSpace, rng: random.Random) -> Action:
    action_type = rng.choice(list(ActionType))
    amount_rule = rng.choice(list(AmountRule))
    return Action(
        action_type=action_type,
        target=space.target_for(action_type),
        amount_rule=amount_rule,
        amount_param=_random_amount_param(amount_rule, rng),
    )


def random_candidate(space: ActionSpace, rng: random.Random, max_actions: int = MAX_ACTIONS) -> Candidate:
    """Uniform action/amount sampling — the honest baseline seed/generator
    shared by both random_search.py and guided_search.py (SPEC §6.3)."""
    n = rng.randint(0, max_actions)
    return Candidate(
        flash_token=rng.choice(space.tokens),
        flash_amount=rng.randint(1, MAX_FIXED_AMOUNT),
        actions=tuple(random_action(space, rng) for _ in range(n)),
    )


# --- Mutation operators. Each: (Candidate, Random, ActionSpace) -> Candidate.

def perturb_amount(c: Candidate, rng: random.Random, space: ActionSpace) -> Candidate:
    """Nudge one action's amount_param (± up to 50% for FIXED, or resample bps)."""
    if not c.actions:
        return c
    i = rng.randrange(len(c.actions))
    a = c.actions[i]
    if a.amount_rule == AmountRule.FIXED:
        factor = rng.uniform(0.5, 1.5)
        new_param = max(0, int(a.amount_param * factor))
    else:
        new_param = _random_amount_param(a.amount_rule, rng)
    actions = c.actions[:i] + (dataclasses.replace(a, amount_param=new_param),) + c.actions[i + 1 :]
    return dataclasses.replace(c, actions=actions)


def change_amount_rule(c: Candidate, rng: random.Random, space: ActionSpace) -> Candidate:
    """Switch a FIXED rule to a state-relative one, or vice versa."""
    if not c.actions:
        return c
    i = rng.randrange(len(c.actions))
    a = c.actions[i]
    if a.amount_rule == AmountRule.FIXED:
        new_rule = rng.choice([AmountRule.PCT_BALANCE, AmountRule.FRAC_RESERVES, AmountRule.PCT_BORROW_CAPACITY])
    else:
        new_rule = AmountRule.FIXED
    new_param = _random_amount_param(new_rule, rng)
    new_action = dataclasses.replace(a, amount_rule=new_rule, amount_param=new_param)
    actions = c.actions[:i] + (new_action,) + c.actions[i + 1 :]
    return dataclasses.replace(c, actions=actions)


def insert_action(c: Candidate, rng: random.Random, space: ActionSpace) -> Candidate:
    """Insert a random valid action, respecting the ≤MAX_ACTIONS bound."""
    if len(c.actions) >= MAX_ACTIONS:
        return c
    pos = rng.randint(0, len(c.actions))
    new_action = random_action(space, rng)
    actions = c.actions[:pos] + (new_action,) + c.actions[pos:]
    return dataclasses.replace(c, actions=actions)


def delete_action(c: Candidate, rng: random.Random, space: ActionSpace) -> Candidate:
    """Drop one action."""
    if not c.actions:
        return c
    i = rng.randrange(len(c.actions))
    actions = c.actions[:i] + c.actions[i + 1 :]
    return dataclasses.replace(c, actions=actions)


def swap_order(c: Candidate, rng: random.Random, space: ActionSpace) -> Candidate:
    """Transpose two adjacent actions."""
    if len(c.actions) < 2:
        return c
    i = rng.randrange(len(c.actions) - 1)
    actions = list(c.actions)
    actions[i], actions[i + 1] = actions[i + 1], actions[i]
    return dataclasses.replace(c, actions=tuple(actions))


def retarget(c: Candidate, rng: random.Random, space: ActionSpace) -> Candidate:
    """Flip a swap direction, or deposit<->withdraw / borrow<->repay."""
    if not c.actions:
        return c
    i = rng.randrange(len(c.actions))
    a = c.actions[i]
    new_type = _OPPOSITE[a.action_type]
    new_action = dataclasses.replace(a, action_type=new_type, target=space.target_for(new_type))
    actions = c.actions[:i] + (new_action,) + c.actions[i + 1 :]
    return dataclasses.replace(c, actions=actions)


def perturb_flash_amount(c: Candidate, rng: random.Random, space: ActionSpace) -> Candidate:
    """Resize the outer flash loan (± up to 50%)."""
    factor = rng.uniform(0.5, 1.5)
    new_amount = max(1, int(c.flash_amount * factor))
    return dataclasses.replace(c, flash_amount=new_amount)


MUTATIONS = (
    perturb_amount,
    change_amount_rule,
    insert_action,
    delete_action,
    swap_order,
    retarget,
    perturb_flash_amount,
)

# A qualifying candidate typically needs several dimensions (a couple of
# action amounts AND the flash size) to land right *simultaneously* — a
# single-mutation step changes only one dimension, so it can wander a
# multi-dimensional target forever without ever landing on it in one shot.
# Havoc stacking (apply 2-4 mutations per step) is the standard fuzzing
# answer to exactly this (AFL's "havoc" stage) — still generic, still never
# steers action *structure* toward the answer, just widens the step size.
HAVOC_MIN_STACK = 2
HAVOC_MAX_STACK = 4


def havoc(c: Candidate, rng: random.Random, space: ActionSpace) -> Candidate:
    """Apply several of the other operators back-to-back in one step."""
    for _ in range(rng.randint(HAVOC_MIN_STACK, HAVOC_MAX_STACK)):
        op = rng.choice(MUTATIONS)
        c = op(c, rng, space)
    return c


ALL_MUTATIONS = MUTATIONS + (havoc,)


def mutate(c: Candidate, rng: random.Random, space: ActionSpace, weights: tuple[float, ...] | None = None) -> Candidate:
    """Pick one operator by weighted RNG (SPEC §6.2) and apply it."""
    op = rng.choices(ALL_MUTATIONS, weights=weights, k=1)[0]
    return op(c, rng, space)
