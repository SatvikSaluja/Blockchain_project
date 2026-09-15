# Benchmark Results (SPEC §12)

| Config | Strategy | N | Discovery rate | Candidates-to-first-exploit (mean±std) | Wall-clock s (mean) | Minimized length (mean) |
|---|---|---|---|---|---|---|
| baseline | random | 3 | 0.00 | nan±nan | nan | — |
| baseline | guided | 3 | 0.00 | nan±nan | nan | — |
| low_liquidity | random | 3 | 0.00 | nan±nan | nan | — |
| low_liquidity | guided | 3 | 0.00 | nan±nan | nan | — |
| high_flash_fee | random | 3 | 0.00 | nan±nan | nan | — |
| high_flash_fee | guided | 3 | 0.00 | nan±nan | nan | — |
| low_capital | random | 3 | 0.00 | nan±nan | nan | — |
| low_capital | guided | 3 | 0.00 | nan±nan | nan | — |
| patched_low_collateral_factor | random | 3 | 0.00 | nan±nan | nan | — |
| patched_low_collateral_factor | guided | 3 | 0.00 | nan±nan | nan | — |

## Honest status of this table

This is a real `--fast` run (N=3, budget=300) — every cell is genuine, not
fabricated. But budget=300 is well below what this scenario needs even on
the *unpatched* baseline (earlier discovery testing found qualifying
exploits anywhere from ~165 to >5000 candidates depending on seed; see
tasks/plan.md's Phase 5 status), so an all-zero table here is expected, not
a bug — SPEC §12: "runs that find nothing within budget are data, not to be
discarded." It does NOT yet show the patched-control signal SPEC §12 asks
for (exploit rate dropping under a conservative collateral factor), because
at this budget *nothing* found anything, unpatched included.

**Targeted patched-control check** (not part of the automated sweep, run
separately to actually answer the question honestly):

- The exact minimized reference exploit (SPEC §4 shape, tuned for the
  baseline's 75% collateral factor) **reverts outright** when replayed
  against `patched_low_collateral_factor` (30%) — the same flash/swap moves
  the price the same way, but PCT_BORROW_CAPACITY resolves to far less USD,
  which isn't enough to repay the flash loan.
- Random search with seed 1337 — which finds a qualifying exploit at
  candidate 165 on the baseline — finds **nothing in 2000 candidates**
  (12x the budget) against the patched scenario.

Both point the same direction: the patch is doing real work, not nothing.
The full N>=20, scenario-default-budget (50,000) sweep — needed for a
properly powered version of this same table — is a documented manual step:

    python -m experiments.benchmark --no-fast
