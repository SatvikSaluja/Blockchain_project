"""Novelty tracking (SPEC §6.4): bucket the economic state into a coarse
tuple, keep a visited-set, reward unseen buckets. This is a coverage signal
analogous to greybox-fuzzing edge coverage — NOT an RL reward.

Buckets are percent-of-baseline rather than raw wei amounts, so the same
bucket width is meaningful regardless of a scenario's absolute scale.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.observer import EconState

DEFAULT_BUCKET_PCT = 5  # round to the nearest 5% of baseline / reference


@dataclass(frozen=True)
class NoveltyBucket:
    reserve_usd_bucket: int
    reserve_col_bucket: int
    oracle_ratio_bucket: int
    debt_bucket: int


class NoveltyTracker:
    """Owns the visited-set for one search run. `score()` must be called
    exactly once per evaluated candidate to mean anything as a coverage
    signal — calling it twice on the same state under-counts novelty."""

    def __init__(self, baseline: EconState, bucket_pct: int = DEFAULT_BUCKET_PCT):
        self._baseline = baseline
        self._bucket_pct = max(1, bucket_pct)
        self._visited: set[NoveltyBucket] = set()

    def _pct_bucket(self, value: int, scale: int) -> int:
        if scale <= 0:
            return 0
        pct = (value * 100) // scale
        return pct // self._bucket_pct

    def bucket_of(self, state: EconState) -> NoveltyBucket:
        debt_scale = self._baseline.reserve_usd or 1
        return NoveltyBucket(
            reserve_usd_bucket=self._pct_bucket(state.reserve_usd, self._baseline.reserve_usd),
            reserve_col_bucket=self._pct_bucket(state.reserve_col, self._baseline.reserve_col),
            oracle_ratio_bucket=self._pct_bucket(state.oracle_price, state.reference_price or 1),
            debt_bucket=self._pct_bucket(state.debt_usd, debt_scale),
        )

    def score(self, state: EconState) -> float:
        """1.0 for a never-before-seen bucket, 0.0 for a repeat."""
        bucket = self.bucket_of(state)
        if bucket in self._visited:
            return 0.0
        self._visited.add(bucket)
        return 1.0

    def __len__(self) -> int:
        return len(self._visited)
