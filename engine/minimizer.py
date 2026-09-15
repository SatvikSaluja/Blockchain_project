"""Delta-minimization (SPEC §8): once a candidate qualifies as an exploit,
shrink it to the smallest/simplest form that still qualifies. Reuses the
exact same execute -> evaluate -> restore path as search — never a
re-implementation — so a minimized attack is guaranteed reproducible.
"""

from __future__ import annotations

import dataclasses
from typing import Callable

from engine.actions import AmountRule, Candidate
from engine.bridge import ExecutionBridge
from engine.evaluator import Evaluator
from engine.observer import Observer

# Round, legible bps values to prefer over whatever exact number binary
# search happens to land on (SPEC §8 step 3: "simplify amount rules toward
# the most legible form"), ascending.
_CANONICAL_BPS = (100, 500, 1000, 2500, 5000, 7500, 9000, 9500, 10000)


def _qualifies(bridge: ExecutionBridge, evaluator: Evaluator, observer: Observer, candidate: Candidate) -> bool:
    """Replay `candidate` and check §7 qualification. Always restores
    afterward, leaving the bridge at a clean baseline either way."""
    result = bridge.execute(candidate)
    state = observer.read()
    ev = evaluator.evaluate(candidate, result, state)
    bridge.restore()
    return ev.is_exploit


def _minimize_action_count(
    bridge: ExecutionBridge, evaluator: Evaluator, observer: Observer, candidate: Candidate
) -> Candidate:
    """Step 1: try removing each action; keep the removal iff still qualifying."""
    actions = list(candidate.actions)
    i = 0
    while i < len(actions):
        trial = dataclasses.replace(candidate, actions=tuple(actions[:i] + actions[i + 1 :]))
        if _qualifies(bridge, evaluator, observer, trial):
            actions = actions[:i] + actions[i + 1 :]
            candidate = trial
        else:
            i += 1
    return candidate


def _shrink_param(
    bridge: ExecutionBridge,
    evaluator: Evaluator,
    observer: Observer,
    low: int,
    high: int,
    apply: Callable[[int], Candidate],
) -> int:
    """Binary search for the smallest value in [low, high] for which
    `apply(value)` still qualifies. Caller guarantees `apply(high)` already
    qualifies (that's the candidate's current value)."""
    if _qualifies(bridge, evaluator, observer, apply(low)):
        return low
    while low < high:
        mid = (low + high) // 2
        if _qualifies(bridge, evaluator, observer, apply(mid)):
            high = mid
        else:
            low = mid + 1
    return high


def _minimize_amounts(
    bridge: ExecutionBridge, evaluator: Evaluator, observer: Observer, candidate: Candidate
) -> Candidate:
    """Step 2: binary-search each action's amount_param, then flash_amount,
    downward toward the smallest value that preserves qualification."""
    for i, a in enumerate(candidate.actions):
        def apply(value: int, i: int = i, a=a) -> Candidate:
            new_action = dataclasses.replace(a, amount_param=value)
            actions = candidate.actions[:i] + (new_action,) + candidate.actions[i + 1 :]
            return dataclasses.replace(candidate, actions=actions)

        best = _shrink_param(bridge, evaluator, observer, 0, a.amount_param, apply)
        candidate = apply(best)

    def apply_flash(value: int) -> Candidate:
        return dataclasses.replace(candidate, flash_amount=value)

    best_flash = _shrink_param(bridge, evaluator, observer, 1, candidate.flash_amount, apply_flash)
    return apply_flash(best_flash)


def _simplify_rules(
    bridge: ExecutionBridge, evaluator: Evaluator, observer: Observer, candidate: Candidate
) -> Candidate:
    """Step 3: for bps-rule actions, prefer the smallest CANONICAL (round,
    legible) bps value that's >= the current shrunk value and still
    qualifies, over whatever exact number binary search landed on."""
    for i, a in enumerate(candidate.actions):
        if a.amount_rule == AmountRule.FIXED:
            continue
        for canonical in _CANONICAL_BPS:
            if canonical < a.amount_param:
                continue
            new_action = dataclasses.replace(a, amount_param=canonical)
            trial = dataclasses.replace(
                candidate, actions=candidate.actions[:i] + (new_action,) + candidate.actions[i + 1 :]
            )
            if _qualifies(bridge, evaluator, observer, trial):
                candidate = trial
                break
    return candidate


def minimize(bridge: ExecutionBridge, evaluator: Evaluator, observer: Observer, candidate: Candidate) -> Candidate:
    """SPEC §8: repeat remove -> shrink -> simplify to a fixed point."""
    while True:
        before = candidate
        candidate = _minimize_action_count(bridge, evaluator, observer, candidate)
        candidate = _minimize_amounts(bridge, evaluator, observer, candidate)
        candidate = _simplify_rules(bridge, evaluator, observer, candidate)
        if candidate == before:
            return candidate
