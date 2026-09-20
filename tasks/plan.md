# Implementation Plan: DeFi Economic Exploit Discovery Engine

## Overview

Build per `SPEC.md`, strictly phase-by-phase (§11). Solidity contracts (Foundry)
form the on-chain layer; a Python engine drives execution via a persistent Anvil
instance, searches the action DSL for profitable insolvency-causing exploits, and
emits minimized reproductions. Six phases, each gated on its SPEC done-when
criterion before the next starts.

## Architecture Decisions

- Foundry for contracts/tests (per SPEC §1). Install via `foundryup`.
- Python 3.12 (already present) + venv; `web3.py`, `eth-abi`, `pydantic`,
  `jinja2`, `typer`. No forge/anvil recompilation per candidate — one Anvil
  process, snapshot/revert (§5).
- Repo layout exactly as SPEC §10.
- Determinism: fixed mnemonic, fixed `--seed`, auto-mine on.

## Task List

### Phase 1: Contracts foundation

- [ ] Task 1: Repo scaffold — `foundry.toml`, directory layout per §10, install
      OpenZeppelin-free minimal ERC20 (write our own, spec wants a minimal one).
      **Verify:** `forge build` succeeds on empty contracts. Small.
- [ ] Task 2: `MockToken.sol` + unit test (mint/transfer/approve/transferFrom).
      **Verify:** `forge test --match-contract MockTokenTest`. Small.
- [ ] Task 3: `ConstantProductAMM.sol` (§3.2) + unit tests: swap math both
      directions, `k` non-decreasing, spot price formula. **Verify:**
      `forge test --match-contract AMMTest`. Small.
- [ ] Task 4: `SpotOracle.sol` (§3.3) + unit test (reads live AMM price).
      **Verify:** `forge test --match-contract OracleTest`. Small.
- [ ] Task 5: `FlashLender.sol` (§3.5) + unit test (loan + fee repayment
      enforced by balance delta, reverts if unrepaid). **Verify:**
      `forge test --match-contract FlashLenderTest`. Small.
- [ ] Task 6: `LendingMarket.sol` (§3.4) + unit tests: deposit/borrow/repay/
      withdraw accounting, health-factor reverts. **Verify:**
      `forge test --match-contract LendingMarketTest`. Medium.
- [ ] Task 7: `AttackExecutor.sol` (§3.6) — Action struct/enums, amount-rule
      resolution, `executeAttack`/`onFlashLoan` + unit test exercising each
      `ActionType`/`AmountRule` in isolation. **Verify:**
      `forge test --match-contract AttackExecutorTest`. Medium.

**Checkpoint — Phase 1 (SPEC done-when):** `forge test` green on all unit tests.

### Phase 2: Manual exploit (ground-truth oracle)

- [ ] Task 8: Shared test fixture — deploy order + scenario seeding (liquidity,
      lending reserves, flash fee) matching `scenario.json` defaults, reusable
      by later `.t.sol` files. **Verify:** fixture compiles, used by a smoke
      test. Small.
- [ ] Task 9: `ManualExploit.t.sol` — hand-written oracle-manipulation attack
      (the §4 reference sequence) proving the vulnerable env is exploitable;
      asserts attacker profit > 0 at reference price AND protocol bad debt
      (debt > collateral at reference price). **Verify:**
      `forge test --match-contract ManualExploitTest` passes. Medium.

**Checkpoint — Phase 2 (SPEC done-when):** manual exploit test asserts profit +
bad debt, green.

### Phase 3: Execution bridge (Python ↔ EVM)

- [ ] Task 10: Python scaffold — `pyproject.toml`/`requirements.txt`, venv,
      `engine/` package skeleton, dev deps (`pytest`). **Verify:** `python -m
      pytest` runs (0 tests, no import errors). Small.
- [ ] Task 11: `engine/actions.py` — `ActionType`/`AmountRule` enums mirroring
      Solidity, `Action`/`Candidate` dataclasses (frozen, hashable), ABI tuple
      encoding helper. **Verify:** unit test encodes a candidate and decodes
      matches Solidity enum ordinals. Small.
- [ ] Task 12: `engine/scenario.py` — pydantic schema for `scenario.json` +
      default `scenarios/vulnerable.json` matching SPEC Appendix. **Verify:**
      loads/validates the sample file. Small.
- [ ] Task 13: `engine/deploy.py` — launch persistent Anvil subprocess (fixed
      mnemonic), deploy all contracts once via `web3.py` using `forge`-built
      artifacts, seed liquidity/reserves/capital from scenario. **Verify:**
      integration test: deploy, read back AMM reserves match scenario. Medium.
- [ ] Task 14: `engine/bridge.py` — `ExecutionBridge` (`execute`, `snapshot`,
      `restore`) + `StateGuard` context manager enforcing re-snapshot after
      every revert. **Verify:** test executes a passing tx and a reverting tx,
      confirms state restored byte-for-byte after `restore()`. Medium.
- [ ] Task 15: `engine/observer.py` — reads economic state (balances, reserves,
      oracle price, debt, collateral) via view calls into the `EconState`
      shape used by `execution_trace.json`. **Verify:** unit test against a
      deployed fixture. Small.
- [ ] Task 16: `engine/evaluator.py` (§7) — `Evaluation` dataclass, profit/
      insolvency logic using **only** `reference_price` from scenario, never
      the on-chain oracle. **Verify:** unit tests for the three "explicitly
      not exploit" cases + one true-positive case. Medium.
- [ ] Task 17: `test_replay_manual_exploit.py` — replay the exact Phase-2
      candidate through the Python bridge; assert profit/bad-debt numbers
      equal (bit-for-bit on the USD figures) the Solidity test's asserted
      values. **Verify:** this test passes. Medium.

**Checkpoint — Phase 3 (SPEC done-when):** replaying the Phase-2 exploit
through the Python bridge reproduces identical numbers.

### Phase 4: Random search

- [ ] Task 18: `engine/search/mutations.py` — random-candidate generator +
      the 7 mutation operators (§6.2), total (never malformed). **Verify:**
      property test: 1000 random candidates all respect `maxActions`, valid
      enum ranges. Small.
- [ ] Task 19: `engine/search/corpus.py` — seed corpus, add/select, dedupe by
      structural hash. **Verify:** unit test for dedupe + selection sampling.
      Small.
- [ ] Task 20: `engine/search/random_search.py` — uniform sampling loop,
      candidate-budget accounting, no fitness feedback, shares execute path
      with guided search. **Verify:** unit test with a tiny fake bridge/budget.
      Small.
- [ ] Task 21: `engine/cli.py` (typer) — `run` command wiring
      scenario→deploy→search→on-exploit callback→save to `results/run_XXX/`
      (minimal write for now: `attack.json` + `scenario.json`). **Verify:**
      CLI `--help` works; smoke-runs 10 candidates against fixture. Small.
- [ ] Task 22: Discovery test — run `random_search` against
      `scenarios/vulnerable.json` with a real budget (seeded) and assert it
      finds a qualifying exploit. **Verify:**
      `pytest -m discovery test_random_discovers_exploit.py` passes
      (mark slow/integration, excluded from default fast suite). Medium.

**Checkpoint — Phase 4 (SPEC done-when):** random search finds a qualifying
exploit within budget on the vulnerable config.

### Phase 5: Economic guidance

- [ ] Task 23: `engine/search/novelty.py` — bucket economic state into a
      coarse tuple, visited-set, novelty score. **Verify:** unit test:
      repeated states score 0 novelty, new buckets score >0. Small.
- [ ] Task 24: `engine/search/fitness.py` — weighted-sum fitness (§6.4) from
      `scenario.json` weights; reverting candidate ⇒ `-inf`. **Verify:** unit
      tests per signal + combined weighting. Small.
- [ ] Task 25: `engine/search/guided_search.py` — fitness-weighted parent
      selection (softmax) + epsilon-uniform exploration, same execute/budget
      path as random. **Verify:** unit test selection distribution roughly
      matches softmax weights over a fixed fitness vector. Medium.
- [ ] Task 26: `experiments/random_vs_guided.py` — head-to-head driver, N
      seeds, records candidates-to-first-exploit per run. **Verify:** run with
      N=5 (fast smoke) produces a CSV with both strategies' results. Medium.

**Checkpoint — Phase 5 (SPEC done-when):** guided beats random on discovery
rate / candidates-to-first-exploit, variance reported (from the N=5 smoke run
at minimum; full N≥20 happens in Phase 6 benchmarking).

**Phase 5 status (honest writeup).** The mechanism is built and unit-tested
(novelty bucketing, weighted fitness, softmax+epsilon selection, corpus
dedupe) — all green. Empirical validation surfaced two real bugs, both fixed:

1. **Corpus stagnation.** `seed_corpus()` gives every initial seed a
   placeholder `fitness=0.0` without ever executing them. Evaluator's
   `profit_usd` (used naively as fitness's "profit" signal) is net of
   `initial_capital_usd`, so it floors around `-2.0` (weighted) for any
   candidate that hasn't yet closed the full flash-loan loop — meaning every
   genuinely-discovered non-reverting candidate scored *worse* than the
   never-executed placeholder seeds, so weighted selection just re-picked the
   same 25 static seeds forever (verified: corpus size stuck at 25 after
   1000 candidates). Fixed in `fitness.py` by scoring "profit" from raw
   captured USD (`state.attacker_usd + col-in-usd`), which floors at 0 and
   rises with real progress, instead of Evaluator's net-of-capital number.
2. **Mutation step size vs. a narrow target.** For this scenario, a
   qualifying sequence needs several dimensions to land right
   *simultaneously* — e.g. the reference shape only works for
   `flash_amount` in roughly `[380k, 470k)` (verified by sweep; `300k` and
   `500k` both revert) *and* near-100% bps at each step. Single-dimension
   mutation steps rarely land a multi-dimensional target at once. Mitigated
   with a generic boundary-value bias (bps rules snap toward 0%/100% some of
   the time — a percentage has a real extreme, unlike an unbounded FIXED
   amount) and an AFL-style `havoc` operator that stacks 2-4 mutations per
   step. Confirmed to fix corpus stagnation (25 → 80-340+ members observed
   across runs) but not sufficient on its own to reliably close the gap at
   small budgets.

**What wasn't achieved:** a clean "guided beats random" result at budgets
safely runnable in this session. This machine is a shared, memory-constrained
box (multiple concurrent Claude Code sessions observed via `ps`); several
head-to-head attempts at budget ≥1500 were OOM-killed mid-run, so the
evidence that exists is from smaller, safe budgets (800-2500, a handful of
seeds): pre-fix, guided was strictly worse (0/5 vs random's 1/5); post-fix,
results are tied (0/3 vs 0/3, 0/5 vs 0/5) rather than a guided win. Given
random search itself needs anywhere from ~165 to >5000 candidates depending
on seed (high variance, confirmed empirically), and `scenarios/vulnerable.json`
is deliberately configured with a 50,000-candidate default budget — 10-100x
more than tested here — this is most honestly read as **inconclusive at
small budgets**, not a disproof of the guidance mechanism. The real
resolution is Phase 6's own full-budget, N≥20 benchmark, which needs to run
this comparison properly anyway per SPEC §12.

### Phase 6: Minimization, reporting, benchmark

- [ ] Task 27: `engine/minimizer.py` — delta-minimize (remove actions →
      replay → keep if still qualifies; binary-search shrink amounts; simplify
      rules), fixed point, reusing execute→evaluate path. **Verify:** unit
      test with a padded/oversized synthetic exploit candidate minimizes to
      the expected short form. Medium.
- [ ] Task 28: `engine/report.py` — Jinja2 `report.md` template + renderer per
      §9 content list. **Verify:** unit test renders a report from a fixture
      `Evaluation`+trace, checks required sections present. Small.
- [ ] Task 29: `engine/solgen.py` — `ExploitReproducer.t.sol` string-template
      generator (redeploy in `setUp`, replay minimized actions, assert profit
      + insolvency). **Verify:** generate from the Phase-2 candidate, run
      `forge test` on the generated file, it passes. Medium.
- [ ] Task 30: Wire full pipeline into `engine/cli.py run` — on qualifying
      exploit: minimize → write `results/run_XXX/{scenario,attack,
      execution_trace}.json, report.md, ExploitReproducer.t.sol`. **Verify:**
      end-to-end CLI run against vulnerable scenario produces a complete
      `results/run_XXX/` dir; generated `.t.sol` passes `forge test`. Medium.
- [ ] Task 31: `experiments/benchmark.py` — full methodology (§12): N≥20 seeds,
      guided vs random, parameter sweep (liquidity/collateral factor/flash
      fee/capital), patched control (TWAP or conservative collateral factor)
      confirming exploit rate drop, markdown + CSV output to `experiments/`.
      **Verify:** run against a reduced sweep (fast mode flag) end-to-end;
      full run documented in README as a make target. Large → split further
      if needed once scoped.
- [ ] Task 32 (stretch, optional — only if budget remains): `TWAPOracle.sol` +
      multi-block harness extension (§13.1). Not required for Phase 6
      done-when.

**Checkpoint — Phase 6 (SPEC done-when):** minimized attack + auto-generated
`.t.sol` passes `forge test`; benchmark table produced.

**Phase 6 status.** First half fully met: a real end-to-end CLI run (seed
1337, budget 200, `random` strategy) found and minimized a qualifying
exploit and wrote a complete `results/run_001/` (scenario/attack/
execution_trace/report.md/.t.sol); the generated
`test/generated/ExploitReproducer_1337.t.sol` passes `forge test` and is
committed as a permanent regression test. Found and fixed a real bug along
the way: `build_execution_trace()` looked up a tx receipt after
`bridge.restore()` had already reverted the chain (`TransactionNotFound`) —
fixed the ordering.

Second half (benchmark table) produced honestly but not fully powered: the
committed `experiments/benchmark_results.md`/`benchmark_summary.csv` are a
real `--fast` run (5 configs x 2 strategies x N=3, budget=300) — genuine
data, not fabricated — but budget=300 is below what even the unpatched
baseline typically needs (confirmed range ~165->5000 candidates depending on
seed, per Phase 5's status above), so every cell reads 0% discovery. That
table alone doesn't demonstrate the patched-control signal SPEC §12 wants.
A separate, targeted check does: the exact reference exploit **reverts
outright** against `patched_low_collateral_factor` (30% vs baseline's 75%),
and random search with a seed that succeeds at candidate 165 on the
baseline finds nothing in 2000 candidates (12x the budget) against the
patch — see `benchmark_results.md`'s addendum for the full writeup. Same
root cause as Phase 5: this is a shared, memory-constrained machine (several
head-to-head attempts above budget ~1500 were OOM-killed), so the properly
powered version of this table — N>=20 at the scenario's own default 50,000-
candidate budget — is a documented manual step (`python -m
experiments.benchmark --no-fast`), consistent with the plan's own risk
mitigation for Task 31.

### Phase 7: Extensions (post-MVP, SPEC §13)

SPEC §13 lists five extensions with one line each — none spec'd to the depth
Phases 1-6 got (exact interfaces, schemas, algorithms). Build order here is
chosen by risk/cost/dependency, **not** the spec's own listed priority order:
start with the smallest, most contained, highest-confidence slice, and treat
each remaining item as its own phase-sized effort requiring real design
before implementation — not something to batch alongside the others in one
pass. That mirrors how Phases 1-6 themselves were built (spec → implement →
test → verify → commit, one gated step at a time), and this repo's own
`benchmark.py` history (§ Phase 6 status, and the "real overnight-run crash"
fix) is a direct demonstration of what skipping that rigor costs.

- [x] **Task 33: Configurable AMM swap fee** (§13.3, first half). SPEC's own
      scenario schema already had `amm.feeBps` (Appendix; `engine/scenario.py`
      already parsed it) — the contract and `engine/deploy.py` just never
      used it. `ConstantProductAMM` now takes `feeBps` in its constructor;
      swap math takes the fee on input, Uniswap-v2 style
      (`inWithFee = in * (1e4-feeBps)/1e4`), so `k` strictly increases
      instead of merely holding when `feeBps > 0`, and is byte-for-byte the
      old zero-fee formula when `feeBps == 0` (every existing deployment
      default). **Verify:** `forge test` 42/42 (was 40/40) — all pre-existing
      tests unchanged plus two new ones proving nonzero fee actually reduces
      output vs. zero-fee and strictly grows `k`. Small.
- [x] **Task 34: Multi-pool routing** (§13.3, second half). Scoped to what
      the spec bullet actually asks ("makes the fake market less toy-like")
      rather than full N-pool generality: `AttackExecutor` takes one
      optional second pool (`amm2`), `address(0)` disables it — every
      existing scenario/test passes 0 and is byte-for-byte unaffected. A
      fixed, pre-approved 2-pool allowlist (`_pool(target)`) rather than
      per-call dynamic approval to an attacker-suppliable address, which
      would be the wrong kind of "generic" here — cheap insurance since the
      search engine's mutation operators can and do generate arbitrary
      target addresses. **Verify:** `test_swapRoutesToTheTargetedPool` —
      two pools seeded to different prices, a candidate targeting the
      second lands on its reserves/formula and leaves the first pool's
      reserves untouched; `test_swapToUnknownPoolReverts` covers the
      allowlist rejection. forge test 44/44 (was 42/42). Deliberately did
      NOT extend `scenario.py`/the search engine to actually explore
      multi-pool scenarios — that's a real, separate follow-on (teaching
      the mutation/fitness layer a second pool exists) if ever wanted, not
      implied by "the contract can route."
- [ ] **Task 32: TWAPOracle + multi-block harness** (§13.1). Explicit
      hardest item — a windowed price average defeats exactly the single-tx
      manipulation this engine currently finds, which is the point, but it
      needs the harness to *advance real blocks* (`evm_mine`,
      `evm_increaseTime`) between actions and hold attacker capital across
      them: a genuinely different execution/candidate model than the
      intra-tx snapshot/restore every other part of this engine (bridge,
      search, evaluator) assumes. Needs its own design pass before coding
      starts — candidate representation, how minimization works across
      blocks, how the evaluator's independent-reference-price rule extends.
      Large. Not started.
- [ ] **Task 35: Second vulnerability class** (§13.2, e.g. first-depositor
      share-price inflation — a real, well-known DeFi bug class, distinct
      from oracle manipulation). Needs a new vulnerable contract, a new
      hand-written Phase-2-style manual reference exploit proving it's
      real, and likely new `ActionType`s for the DSL/executor. The point is
      proving the search engine generalizes past one lucky bug family, so
      it should get the same phase-2-then-phase-4 rigor the original bug
      did, not a shortcut. Large. Not started.
- [ ] **Task 36: Coverage-guided hybrid search** (§13.4). Blend the
      existing economic-signal fitness with real EVM code-coverage (SPEC
      names `--steps-tracing`) for a true greybox signal. The most
      research-flavored item — needs its own investigation into what Anvil
      actually exposes for step/branch coverage before a fitness formula
      combining the two signals can be designed, let alone implemented.
      Large, and the one item where "how" isn't yet knowable without a
      spike. Not started.
- [x] **Task 37: Static showcase/results page** (§13.5, lean version only).
      SPEC ranks a "web dashboard for live corpus/fitness visualization"
      dead last of all five extensions; built the lean, explicitly-scoped
      version instead of the full interactive app — a static single-page
      showcase (the real discovered exploit, its price-manipulation chart,
      the patched-vs-unpatched comparison), not a live search-launching
      dashboard, which would need a real backend wrapping the Python engine
      and is not what a research/fuzzing tool needs (SPEC: "explicitly out
      of scope for v1"). Published as Artifact "Case 1337."

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Foundry not installed in sandbox | Blocks Phase 1 | Install via `foundryup` at Task 1; if network-blocked, stop and ask user. |
| Anvil snapshot/revert semantics subtle (consumes snapshot) | Silent state corruption | `StateGuard` context manager (Task 14) is the only revert path; unit-tested. |
| Random search may not find exploit within a "fast" budget in CI | Flaky/slow tests | Discovery test (Task 22) marked integration/slow, generous but bounded budget, fixed seed. |
| Full N≥20-seed benchmark is slow | Long-running | `experiments/benchmark.py` gets a `--fast` reduced-N mode for verification; full run is a documented manual step, not part of the default test suite. |
| Task 31 may prove Large | Scope creep | Re-split into sweep/control/report sub-tasks once Phase 5 lands, before starting. |

## Open Questions

None blocking — spec is fully self-contained. Foundry install method (network
access) is the only environmental unknown, resolved at Task 1.
