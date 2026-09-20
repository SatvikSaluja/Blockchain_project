# Todo — DeFi Economic Exploit Discovery Engine

Full task detail (acceptance criteria, verification, files) lives in
`tasks/plan.md`. This file tracks completion state only.

## Phase 1: Contracts foundation
- [x] Task 1: Repo scaffold (foundry.toml, layout)
- [x] Task 2: MockToken.sol + test
- [x] Task 3: ConstantProductAMM.sol + tests
- [x] Task 4: SpotOracle.sol + test
- [x] Task 5: FlashLender.sol + test
- [x] Task 6: LendingMarket.sol + tests
- [x] Task 7: AttackExecutor.sol + test
- [x] Checkpoint: `forge test` green on unit tests (36/36 passing)

## Phase 2: Manual exploit
- [x] Task 8: Shared test fixture (deploy + seed)
- [x] Task 9: ManualExploit.t.sol (profit + bad debt asserted)
- [x] Checkpoint: manual exploit test green

## Phase 3: Execution bridge
- [x] Task 10: Python scaffold
- [x] Task 11: engine/actions.py (DSL, encoding)
- [x] Task 12: engine/scenario.py + scenarios/vulnerable.json
- [x] Task 13: engine/deploy.py (Anvil + deploy-once + seed)
- [x] Task 14: engine/bridge.py (ExecutionBridge, StateGuard)
- [x] Task 15: engine/observer.py
- [x] Task 16: engine/evaluator.py (§7)
- [x] Task 17: replay Phase-2 exploit via bridge, numbers match
- [x] Checkpoint: bridge replay reproduces identical numbers (bit-for-bit)

## Phase 4: Random search
- [x] Task 18: engine/search/mutations.py
- [x] Task 19: engine/search/corpus.py
- [x] Task 20: engine/search/random_search.py
- [x] Task 21: engine/cli.py (run command)
- [x] Task 22: discovery test — random search finds exploit
- [x] Checkpoint: random search finds qualifying exploit within budget (~165/2000 candidates, seed 1337)

## Phase 5: Economic guidance
- [x] Task 23: engine/search/novelty.py
- [x] Task 24: engine/search/fitness.py
- [x] Task 25: engine/search/guided_search.py
- [x] Task 26: experiments/random_vs_guided.py (N=5 smoke)
- [~] Checkpoint: guided beats random, variance reported — see
      tasks/plan.md "Phase 5 status" for the honest empirical writeup: two
      real bugs were found and fixed during validation, but a clean guided
      win was NOT demonstrated at the budgets safely testable in this
      session. Deferred to Phase 6's full-budget benchmark.

## Phase 6: Minimization, reporting, benchmark
- [x] Task 27: engine/minimizer.py
- [x] Task 28: engine/report.py (report.md via Jinja2)
- [x] Task 29: engine/solgen.py (ExploitReproducer.t.sol generator)
- [x] Task 30: wire full pipeline into CLI, end-to-end results/run_XXX
- [x] Checkpoint (partial): minimized attack + generated .t.sol passes forge
      test — verified end-to-end (run_001, seed 1337, ExploitReproducer_1337.t.sol
      PASSES). Full checkpoint (benchmark table) needs Task 31.
- [x] Task 31: experiments/benchmark.py (full §12 methodology, --fast mode)
- [ ] Task 32 (stretch, optional): TWAPOracle + multi-block harness
- [~] Checkpoint: minimized attack + generated .t.sol passes forge test (DONE)
      ; benchmark table produced (DONE, but --fast/N=3/budget=300 shows 0%
      everywhere — not enough budget to show the patched-control signal on
      its own). See tasks/plan.md "Phase 6 status" for the full honest
      writeup, including a targeted check that DOES show the patch working
      (reference exploit reverts under it; search fails to find anything in
      12x the budget that succeeds on baseline). Full N>=20 default-budget
      run is a documented manual step.

## Phase 7: Extensions (post-MVP, SPEC §13) — build order chosen by
   risk/cost, not the spec's listed order; see tasks/plan.md "Phase 7" for
   the full reasoning per task.
- [x] Task 33: Configurable AMM swap fee (§13.3, first half) — ConstantProductAMM
      takes feeBps; scenario schema already had the field, was never wired
      to the contract until now. Default 0 everywhere existing, so this is
      purely additive (forge test 42/42, all pre-existing behavior
      byte-for-byte unchanged).
- [ ] Task 34: Multi-pool routing (§13.3, second half) — AttackExecutor
      currently hardcodes one immutable `amm` and rejects any other target;
      needs generalizing to swap against an arbitrary pool address. Not
      started.
- [ ] Task 32: TWAPOracle + multi-block harness (§13.1) — stretch, explicit
      SPEC-designated hardest item (different execution model: block-
      advancing, not snapshot/restore). Not started.
- [ ] Task 35: Second vulnerability class (§13.2, e.g. first-depositor
      share-price inflation) — proves the search engine generalizes beyond
      one bug family. Not started.
- [ ] Task 36: Coverage-guided hybrid search (§13.4) — EVM step-tracing
      blended with the existing economic fitness signal. Not started.
- [x] Task 37: Static showcase/results page (§13.5, lean version only — the
      spec's own lowest-priority item, and explicitly NOT the live
      interactive dashboard). Published as artifact "Case 1337."
