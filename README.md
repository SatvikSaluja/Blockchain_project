# DeFi Economic Exploit Discovery Engine

[![CI](https://github.com/SatvikSaluja/Blockchain_project/actions/workflows/ci.yml/badge.svg)](https://github.com/SatvikSaluja/Blockchain_project/actions/workflows/ci.yml)

A local, execution-driven fuzzer that discovers profitable economic exploits
against a small DeFi ecosystem: real Solidity contracts on a local EVM
(Anvil), a Python search engine that proposes and mutates transaction
sequences, and an evaluator that judges profit/insolvency at a fixed
reference price — never the contracts' own (manipulable) oracle.

This is **fitness-guided evolutionary search**, not RL and not Bayesian
optimization. Full design rationale is in [`SPEC.md`](SPEC.md); build
history and honest status notes (including what worked, what didn't, and
why) are in [`tasks/plan.md`](tasks/plan.md).

## Primary result

Given a vulnerable AMM + lending setup it was never told how to attack, the
engine independently finds and reproduces a profitable oracle-manipulation
exploit — verified end to end: `results/run_001/` and
[`test/generated/ExploitReproducer_1337.t.sol`](test/generated/ExploitReproducer_1337.t.sol)
(a passing `forge test`) were both produced by a real, unmodified CLI run,
not hand-written. A guided walkthrough of this exact finding — the price
chart, full execution trace, and the patched-vs-unpatched comparison — is
published at [claude.ai/artifact/Pw6sF8eALFSJTjorTYKoZn](https://claude.ai/artifact/Pw6sF8eALFSJTjorTYKoZn)
("Case 1337").

## Setup

```bash
curl -L https://foundry.paradigm.xyz | bash && foundryup   # if not installed
forge install                                               # forge-std

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Running

```bash
# Solidity unit tests + the hand-written ground-truth exploit
forge test

# Python: fast suite (no live Anvil needed for most of it)
pytest -m "not discovery"

# Python: everything, including live-Anvil integration/discovery tests (slow)
pytest

# Search for an exploit against the vulnerable scenario; on success, writes
# results/run_XXX/{scenario,attack,execution_trace}.json, report.md, and
# ExploitReproducer.t.sol (also copied into test/generated/)
python -m engine.cli scenarios/vulnerable.json --strategy random --budget 50000

# Guided (fitness-weighted) search instead of uniform random
python -m engine.cli scenarios/vulnerable.json --strategy guided --budget 50000

# Guided vs random head-to-head (SPEC §6.3)
python -m experiments.random_vs_guided --n-seeds 20 --budget 2000

# Full SPEC §12 benchmark: parameter sweep + patched control, N seeds
python -m experiments.benchmark --no-fast   # full rigor: can take hours
python -m experiments.benchmark             # --fast: reduced N/budget, verifiable in minutes
```

## Repository layout

See `SPEC.md` §10 for the authoritative layout; briefly:

- `contracts/` — the vulnerable protocol (AMM, lending market, flash lender,
  oracle) and `AttackExecutor`, the on-chain DSL interpreter.
- `test/` — Foundry unit tests, the hand-written ground-truth exploit
  (`ManualExploit.t.sol`), and `test/generated/` for auto-produced
  reproductions.
- `engine/` — the Python side: DSL/encoding, the execution bridge
  (snapshot/restore against a persistent Anvil), observer, evaluator,
  `engine/search/` (mutations, corpus, random and guided search, fitness,
  novelty), minimizer, reporting, and the CLI.
- `scenarios/vulnerable.json` — the scenario config; its numbers are kept in
  sync with `test/Fixture.sol`'s constants.
- `experiments/` — benchmark drivers and their output artifacts.
- `results/` — per-run output (gitignored; `test/generated/` is where a
  finding becomes a permanent regression test).

## Honest status

This was built and validated incrementally, phase-by-phase, with real bugs
found and fixed along the way rather than assumed away — see
`tasks/plan.md`'s per-phase "status" notes for the specifics, including:

- Two real search-engine bugs found during Phase 5 validation (a corpus
  fitness-floor bug that made guided search permanently prefer never-executed
  placeholder seeds over genuine discoveries, and a mutation-step-size issue
  against a narrow multi-dimensional target), both fixed.
- The full SPEC §12 benchmark (N≥20 seeds, showing guided decisively beating
  random and the patched-control exploit rate dropping) has been attempted
  repeatedly at the scenario's default 50,000-candidate budget and failed
  every time for reasons unrelated to the science: a launch-mechanics
  mistake, the process dying with its shell session, a real RPC-hang bug in
  `engine/bridge.py` (since fixed — see git history), and a self-inflicted
  bug from rebuilding contracts while the run was still in flight (also
  fixed). After 5 straight failures of the full-budget version, switched to
  a capped budget (`--budget 8000`, still N=20 as SPEC requires) to get a
  real result that can actually finish inside one session — see git history
  / `tasks/plan.md` for the blow-by-blow. What's committed today: a genuine
  `--fast` run (small N/budget, honestly all-zero at that budget) plus a
  separate, targeted check that *does* show the patch working (the
  reference exploit reverts outright under it; a seed that succeeds at
  candidate 165 on the baseline finds nothing in 12x the budget against the
  patch). The full 50,000-budget run is one documented command away:
  `python -m experiments.benchmark --no-fast`.
- Task 32 (TWAP oracle + multi-block harness, SPEC §13.1) is explicitly
  post-MVP/stretch and not built.
- Post-MVP extensions (SPEC §13), tracked as "Phase 7" in `tasks/plan.md`:
  configurable AMM swap fee (Task 33) and 2-pool swap routing (Task 34) are
  built and tested — routing is proven at the contract level (a candidate
  can target either pool) but the search engine itself isn't yet taught
  that a second pool can exist in any real scenario, so it can't discover
  cross-pool exploits today. TWAP oracle, a second vulnerability class, and
  coverage-guided search remain unbuilt.

## License

[MIT](LICENSE)
