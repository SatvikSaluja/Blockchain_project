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
