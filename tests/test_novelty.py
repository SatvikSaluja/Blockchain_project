from engine.observer import EconState
from engine.search.novelty import NoveltyTracker

BASELINE = EconState(
    attacker_usd=0,
    attacker_col=0,
    reserve_usd=1_000_000 * 10**18,
    reserve_col=1_000_000 * 10**18,
    oracle_price=10**18,
    reference_price=10**18,
    debt_usd=0,
    collateral_col=0,
)


def _state(**overrides) -> EconState:
    return EconState(**{**BASELINE.__dict__, **overrides})


def test_first_sighting_of_a_bucket_scores_one():
    tracker = NoveltyTracker(BASELINE)
    assert tracker.score(BASELINE) == 1.0
    assert len(tracker) == 1


def test_repeated_state_scores_zero():
    tracker = NoveltyTracker(BASELINE)
    tracker.score(BASELINE)
    assert tracker.score(BASELINE) == 0.0
    assert len(tracker) == 1


def test_meaningfully_different_state_scores_one():
    tracker = NoveltyTracker(BASELINE)
    tracker.score(BASELINE)

    moved = _state(reserve_usd=1_400_000 * 10**18, reserve_col=714_285 * 10**18, oracle_price=1_96 * 10**16)
    assert tracker.score(moved) == 1.0
    assert len(tracker) == 2


def test_tiny_noise_within_the_same_bucket_scores_zero():
    tracker = NoveltyTracker(BASELINE, bucket_pct=5)
    tracker.score(BASELINE)

    # +0.001% move — well inside the 5%-wide bucket, should not count as new.
    barely_moved = _state(reserve_usd=BASELINE.reserve_usd + 10**16)
    assert tracker.score(barely_moved) == 0.0
    assert len(tracker) == 1


def test_bucket_of_is_scale_invariant_across_baselines():
    small = EconState(**{**BASELINE.__dict__, "reserve_usd": 1_000 * 10**18, "reserve_col": 1_000 * 10**18})
    tracker_big = NoveltyTracker(BASELINE)
    tracker_small = NoveltyTracker(small)

    # Both are "50% up" relative to their own baseline -> same bucket shape.
    moved_big = _state(reserve_usd=BASELINE.reserve_usd * 3 // 2)
    moved_small = EconState(**{**small.__dict__, "reserve_usd": small.reserve_usd * 3 // 2})

    assert tracker_big.bucket_of(moved_big).reserve_usd_bucket == tracker_small.bucket_of(moved_small).reserve_usd_bucket
