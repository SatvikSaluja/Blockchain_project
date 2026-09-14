# DeFi Economic Exploit Discovery Engine — Build Specification

> **Purpose of this file.** This is a complete engineering spec intended to be
> consumed by Claude Code as the source of truth for the build. Drop it in the
> repo root as `SPEC.md`. Build strictly phase-by-phase (§11). Do **not** skip
> ahead to the search engine before the manual exploit in Phase 2 passes — that
> exploit is the ground-truth oracle for everything downstream.

---

## 0. Mission & Scope

Build a **local, execution-driven fuzzer that discovers profitable economic
exploits** against a small DeFi ecosystem. The engine proposes transaction
sequences, executes them against *real* Solidity contracts on a local EVM,
measures the resulting economic state, and — when a sequence is both valid and
profitable *and* leaves the protocol insolvent — minimizes it and emits a
self-contained Solidity reproduction test plus a human-readable report.

This is **not** a static analyzer and **not** a symbolic executor. It is a
**greybox, economically-guided evolutionary search** over an action DSL, with a
fitness function derived from observed on-chain economic signals. Be precise
about that framing everywhere in code comments and docs: it is fitness-guided
mutation search, not RL and not Bayesian optimization. Do not overstate it.

**Primary success milestone (Phase 4+):** *Given a vulnerable AMM + lending
setup the engine was not told how to attack, it independently finds and
reproduces a profitable oracle-manipulation exploit.*

---

## 1. Tech Stack & Toolchain

| Layer | Choice | Notes |
|---|---|---|
| Contracts | Solidity `^0.8.24` | Overflow checks on by default; do not use `unchecked` in accounting paths. |
| EVM / execution | **Anvil** (Foundry) as a **long-running process** | Deploy once, snapshot, replay-restore per candidate. See §5 — this is the single most important performance decision. |
| Contract build/test | **Foundry** (`forge`) | Unit tests, invariant tests, and the *generated* reproduction tests all run under `forge test`. |
| Gas accounting | Foundry gas metering / tx-receipt `gasUsed` | **Never** hand-estimate gas. Convert to USD via configurable `gasPriceGwei` × `ethPriceUsd` in scenario config. |
| Search / orchestration | **Python 3.11+** | `web3.py` for RPC, `eth-abi` for action encoding, `pydantic` for schemas, `dataclasses` for candidates. |
| Reporting | Python (Jinja2 for `report.md`, string templating for `.t.sol`) | |
| CLI | `typer` or `argparse` | Dashboard is explicitly out of scope for v1. |

**Determinism requirement:** every run is seeded. `--seed` controls all Python
RNG. Anvil is launched with a fixed mnemonic and `--no-mining` disabled (auto-mine
on) so tx ordering is deterministic. Record the seed in every result artifact.

---

## 2. System Architecture

```
                         scenario.json
                              │
                              ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Orchestrator (Python)                                     │
   │                                                            │
   │   corpus ──► select ──► mutate ──► Candidate               │
   │      ▲                                  │                  │
   │      │                                  ▼                  │
   │   Evaluator ◄── Observer ◄──── Execution Bridge            │
   │      │  (fitness + exploit test)         │  (web3 → RPC)   │
   │      │                                   ▼                  │
   │      └── exploit? ──► Minimizer ──► Reporter               │
   └──────────────────────────────────────────────────────────┘
                              │                    │
                              ▼                    ▼
                   Long-running Anvil        results/run_XXX/
              (contracts deployed once,       ├─ scenario.json
               snapshot/revert per            ├─ attack.json
               candidate)                     ├─ execution_trace.json
                    │                          ├─ report.md
                    ▼                          └─ ExploitReproducer.t.sol
        ConstantProductAMM · SpotOracle
        LendingMarket · FlashLender
        MockToken×2 · AttackExecutor
```

The **contracts execute the attack**; Python never simulates EVM semantics. The
Python side only: encodes candidates, submits one transaction per candidate,
reads state back through view calls, scores, and restores state.

---

## 3. On-Chain Layer — Contract Specifications

All monetary values use `1e18` fixed-point. Prices are expressed as *USD per 1
COL*, `1e18`-scaled. Basis points (`bps`, `1e4` = 100%) are used for factors.

Deploy order: `USD` token → `COL` token → `AMM` → `Oracle(AMM)` →
`LendingMarket(oracle, USD, COL)` → `FlashLender(USD, COL)` →
`AttackExecutor(all of the above)`. Seed AMM liquidity and lending-market USD
reserves from `scenario.json`.

### 3.1 `MockToken` (ERC-20)

Minimal ERC-20 with open `mint(address,uint256)` for test setup only.

```solidity
function mint(address to, uint256 amount) external;         // setup only
function balanceOf(address) external view returns (uint256);
function transfer(address,uint256) external returns (bool);
function approve(address,uint256) external returns (bool);
function transferFrom(address,address,uint256) external returns (bool);
```

Deploy two instances: `USD` (borrowable), `COL` (collateral).

### 3.2 `ConstantProductAMM`

Uniswap-v2-style `x·y = k`. **No swap fee in v1** (add a configurable fee later;
a zero-fee pool makes the manipulation math cleaner to validate by hand).

```solidity
constructor(address usd, address col);

function addLiquidity(uint256 usdAmount, uint256 colAmount) external;   // setup
function getReserves() external view returns (uint256 rUsd, uint256 rCol);

// Exact-in swaps; returns amount out. Reverts on zero-out or k-violation.
function swapUsdForCol(uint256 usdIn) external returns (uint256 colOut);
function swapColForUsd(uint256 colIn) external returns (uint256 usdOut);

// Spot price = USD per COL, 1e18-scaled: rUsd * 1e18 / rCol
function spotPrice() external view returns (uint256);
```

Constant-product out: `out = (rOut * in) / (rIn + in)` (zero-fee form). Enforce
`k_after >= k_before` after transfers.

### 3.3 `SpotOracle` (and `TWAPOracle` — later)

```solidity
constructor(address amm);
function price() external view returns (uint256);   // == amm.spotPrice()
```

`SpotOracle.price()` reads live reserves → **this is the vulnerability**: an
attacker moves reserves within the same transaction and the lending market trusts
the result.

`TWAPOracle` (Phase-6 extension): accumulate `price · elapsed` per block, expose a
windowed average. Requires the harness to *advance blocks* (§13), not just
snapshot within one block — materially harder. Not part of the MVP.

### 3.4 `LendingMarket`

Single-collateral (COL), single-borrow (USD) market. Prices come from the
injected oracle.

```solidity
constructor(address oracle, address usd, address col);

function depositCollateral(uint256 colAmount) external;
function borrow(uint256 usdAmount) external;             // reverts if unhealthy
function repay(uint256 usdAmount) external;
function withdrawCollateral(uint256 colAmount) external; // reverts if unhealthy

// Views for the observer:
function collateralOf(address) external view returns (uint256);
function debtOf(address) external view returns (uint256);

// Parameters from scenario.json:
uint256 public collateralFactorBps;    // e.g. 7500 = 75% max LTV
```

Accounting (all in USD, `1e18`):

```
colValueUsd = collateralOf(user) * oracle.price() / 1e18
maxDebtUsd  = colValueUsd * collateralFactorBps / 1e4
borrow(x): require(debtOf(user) + x <= maxDebtUsd)
```

Liquidation is **not required** for the MVP exploit — bad debt is detected by the
*evaluator* using an independent reference price (§7), not by an on-chain
liquidation call. (Optional liquidation function can come later for richer
scenarios.)

### 3.5 `FlashLender`

Single-tx flash loan with mandatory repayment + fee, enforced by balance delta.

```solidity
constructor(address usd, address col);
function flashLoan(address token, uint256 amount, bytes calldata data) external;
// Calls back AttackExecutor.onFlashLoan(token, amount, fee, data);
// after callback, requires balanceOf(this) >= pre + fee, else revert.

uint256 public feeBps;   // from scenario.json, e.g. 9 = 0.09%
```

### 3.6 `AttackExecutor`

The on-chain interpreter for a candidate. Receives an ABI-encoded action array,
opens the flash loan (fixed outer wrapper in v1), runs the inner actions inside
the callback, then repayment is asserted by `FlashLender`.

```solidity
struct Action {
    uint8   actionType;   // enum ActionType
    address target;       // token or market address (context-dependent)
    uint8   amountRule;   // enum AmountRule
    uint256 amountParam;  // absolute amount OR bps, per rule
}

enum ActionType { SWAP_USD_FOR_COL, SWAP_COL_FOR_USD, DEPOSIT_COL, BORROW_USD, REPAY_USD, WITHDRAW_COL }
enum AmountRule { FIXED, PCT_BALANCE, FRAC_RESERVES, PCT_BORROW_CAPACITY }

// Entry point. flashToken/flashAmount define the fixed wrapper; `actions`
// are executed inside onFlashLoan. Reverts propagate (candidate = revert).
function executeAttack(
    address flashToken,
    uint256 flashAmount,
    Action[] calldata actions
) external;

function onFlashLoan(address token, uint256 amount, uint256 fee, bytes calldata data) external;
```

**Amount-rule resolution** happens on-chain at execution time against *live*
state (this is what makes state-relative amounts meaningful across scenarios):

| Rule | Resolved amount |
|---|---|
| `FIXED` | `amountParam` (absolute, 1e18) |
| `PCT_BALANCE` | `token.balanceOf(this) * amountParam / 1e4` |
| `FRAC_RESERVES` | `(relevant AMM reserve) * amountParam / 1e4` |
| `PCT_BORROW_CAPACITY` | `(maxDebtUsd − debtUsd) * amountParam / 1e4` |

Clamp each resolved amount to available balance/capacity to avoid trivially
reverting on rounding.

---

## 4. Attack Representation (Action DSL)

A **candidate** is: `(flashToken, flashAmount, [Action, …])` with the inner list
bounded to **≤ 6 actions** in the MVP. The flash wrapper is fixed (always opened,
always repaid-attempted) so search focuses on the economically interesting inner
program and repayment is never accidentally dropped.

Python-side representation:

```python
@dataclass(frozen=True)
class Action:
    action_type: ActionType
    target: str            # checksummed address
    amount_rule: AmountRule
    amount_param: int      # absolute (wei) or bps

@dataclass(frozen=True)
class Candidate:
    flash_token: str
    flash_amount: int
    actions: tuple[Action, ...]
```

`Candidate` is hashable/immutable so the corpus can dedupe structurally
identical candidates.

**Reference exploit** (the shape Phase 2 builds by hand and the engine should be
able to rediscover — *do not hardcode it into the search*):

```
FLASH_BORROW(USD, F)
  SWAP_USD_FOR_COL(FRAC_RESERVES or PCT_BALANCE)   # push COL price up
  DEPOSIT_COL(PCT_BALANCE)                          # deposit inflated collateral
  BORROW_USD(PCT_BORROW_CAPACITY)                   # over-borrow at bad price
  SWAP_COL_FOR_USD(PCT_BALANCE)                     # unwind
REPAY_FLASH_LOAN(F + fee)
```

---

## 5. Execution Bridge (Python ↔ EVM) — **read carefully**

**Do not recompile or redeploy per candidate.** The naive `forge test`-per-
candidate loop is ~1000× too slow and will make the benchmark meaningless.
Instead:

1. Launch **one** persistent Anvil (`anvil --mnemonic <fixed> --silent`).
2. Deploy all contracts **once**; seed liquidity/reserves from `scenario.json`.
3. Fund the attacker EOA with the modeled initial capital.
4. Take a baseline snapshot: `snap = evm_snapshot()`.
5. **Per candidate:**
   a. ABI-encode `actions` (`eth-abi`), submit **one** tx:
      `AttackExecutor.executeAttack(flashToken, flashAmount, actions)`.
   b. Capture receipt (`status`, `gasUsed`) — a revert ⇒ candidate invalid.
   c. Read economic state via view calls (§6 Observer).
   d. **Restore:** `evm_revert(snap)` **then immediately** `snap = evm_snapshot()`.

> ⚠️ **Anvil snapshot gotcha:** reverting to a snapshot *consumes* it and
> invalidates all snapshots taken after it. Always re-`evm_snapshot()` right
> after every `evm_revert`. Wrap this in a `with StateGuard():` context manager
> so no code path can forget it.

The bridge exposes:

```python
class ExecutionBridge:
    def execute(self, c: Candidate) -> ExecResult: ...   # submits tx, returns receipt + revert flag
    def snapshot(self) -> None: ...
    def restore(self) -> None: ...                        # revert + re-snapshot
```

Encoding of the `Action[]` uses the tuple ABI type
`(uint8,address,uint8,uint256)[]`.

---

## 6. Search Engine

### 6.1 Candidate lifecycle

```python
corpus = seed_corpus(scenario)     # a handful of hand-shaped + random seeds
while budget.remaining():          # budget measured in CANDIDATES, not seconds
    parent = select(corpus)
    child  = mutate(parent, rng)
    bridge.restore()
    result = bridge.execute(child)
    ev     = evaluator.evaluate(child, result, observer.read())
    if ev.is_exploit:
        save_and_minimize(child, ev)
        # keep searching (find multiple / shorter); do not early-exit unless configured
    elif ev.is_interesting:
        corpus.add(child, ev.fitness)
    budget.tick()
```

### 6.2 Mutation operators (`engine/search/mutations.py`)

Each mutation returns a *new* `Candidate`. Choose operator by weighted RNG:

- `perturb_amount` — nudge an `amount_param` (± up to 50%, or resample bps).
- `change_amount_rule` — switch a `FIXED` to a state-relative rule or vice versa.
- `insert_action` — insert a random valid action (respect ≤6 bound).
- `delete_action` — drop one action.
- `swap_order` — transpose two adjacent actions.
- `retarget` — change a swap direction / deposit-vs-withdraw.
- `perturb_flash_amount` — resize the outer flash loan.

Keep operators total (never emit malformed candidates); validity of the
*economics* is decided by execution, not by the mutator.

### 6.3 Corpus & selection (`engine/search/`)

- `random_search.py` — uniform action/amount sampling, **no** fitness feedback.
  This is the honest baseline for §12. It must share the exact same execution
  path, budget accounting, and action space as the guided search.
- `guided_search.py` — fitness-weighted parent selection + novelty retention.

`select()` samples parents with probability ∝ fitness (e.g. softmax over scores),
with an ε fraction of uniform picks to preserve exploration.

### 6.4 Economic guidance / fitness function

Fitness **ranks** candidates for further exploration; it does **not** declare an
exploit (that's the evaluator's job, §7). Combine normalized signals:

| Signal | Rationale | Source |
|---|---|---|
| `|oracle_price − reference_price| / reference_price` | price manipulation magnitude | observer + config |
| `Δborrow_capacity / capital_deployed` | unusually cheap credit | observer |
| `debt_usd − recoverable_collateral_usd` | emerging bad debt | observer (ref price) |
| `attacker_net_usd_delta` | progress toward profit | observer (ref price) |
| novelty of `(coarse economic state)` | encourages exploration | corpus-side hash of bucketed state |

Novelty: bucket the economic state (e.g. rounded reserves, rounded oracle/ref
ratio, rounded debt) into a tuple, keep a visited-set, reward unseen buckets.
This is a coverage signal analogous to greybox fuzzing coverage — call it that,
not "RL reward."

Fitness = weighted sum with weights in `scenario.json` so ablations are config-
only. A reverting candidate gets fitness `−∞` (dropped).

---

## 7. Evaluator & Success Criteria

**The one design rule that makes this rigorous:** the evaluator judges profit and
solvency using an **independent, fixed `reference_price`** from
`scenario.json` — *never* the contracts' own (manipulable) oracle. Otherwise a
manipulated oracle makes the evaluator report phantom profit (circular). The
contracts keep using their configured oracle; the *judge* does not.

A candidate is a **successful exploit** iff **all** hold:

1. The full transaction executed (no revert).
2. The flash loan + fee were repaid (implied by non-revert given §3.5).
3. Attacker **net profit > 0** in USD at `reference_price`, after:
   - converting all residual liquid attacker assets (COL) to USD at reference price,
   - deducting initial capital,
   - deducting modeled gas cost (`gasUsed × gasPriceGwei × ethPriceUsd`),
   - accounting for any residual obligations.
4. The lending market is left **insolvent**: `debt_usd > collateral_usd` valued
   at `reference_price` (i.e. protocol bad debt exists).

Explicitly **not** exploits (encode as tests):

- A transient increase in borrow capacity → *signal only*.
- A reverted tx → its state changes never persisted → not an exploit.
- Attacker profit that comes only from mispricing *in their own favor at the
  reference price with no protocol bad debt* → not the target class (tighten via
  criterion 4).

```python
@dataclass
class Evaluation:
    is_exploit: bool
    is_interesting: bool
    fitness: float
    attacker_profit_usd: int
    protocol_bad_debt_usd: int
    violated_property: str | None
```

---

## 8. Minimization

Once a candidate qualifies, delta-minimize before reporting:

1. Try removing each action (one at a time); replay from baseline snapshot; keep
   the removal iff the exploit still qualifies under §7.
2. Shrink amounts (binary-search `amount_param` downward toward the smallest
   value that preserves success).
3. Simplify amount rules toward the most legible form where it doesn't break the
   exploit.
4. Repeat to a fixed point.

Minimization uses the **exact same execute→evaluate path** as search — never a
re-implementation — so a minimized attack is guaranteed reproducible.

---

## 9. Reporting & Test Generation

On a confirmed, minimized exploit, write to `results/run_XXX/`:

```
scenario.json          # exact config used (echoed, incl. seed)
attack.json            # minimized candidate (schema in Appendix)
execution_trace.json   # per-action pre/post: balances, reserves, oracle price, debt, collateral, gasUsed
report.md              # human-readable (Jinja2)
ExploitReproducer.t.sol# self-contained Foundry test
```

`report.md` must contain: initial liquidity & lending params; exact minimized
actions + resolved amounts; before/after balances, reserves, oracle vs reference
price, debt/collateral; attacker profit (USD) and protocol bad debt (USD); the
violated property; and reproduction instructions.

`ExploitReproducer.t.sol` must: redeploy the scenario in `setUp()`, execute the
minimized action sequence, and `assert` both the attacker profit and the
protocol-insolvency condition — so `forge test` re-proves the finding from
scratch, independent of Python.

---

## 10. Repository Layout

```
defi-exploit-discovery/
├── contracts/
│   ├── tokens/MockToken.sol
│   ├── amm/ConstantProductAMM.sol
│   ├── lending/LendingMarket.sol
│   ├── oracles/SpotOracle.sol          # TWAPOracle.sol later
│   ├── FlashLender.sol
│   └── AttackExecutor.sol
├── test/
│   ├── unit/                            # accounting + swap math
│   ├── invariants/                      # Foundry invariant tests (§ below)
│   └── generated/                       # emitted ExploitReproducer.t.sol files
├── engine/
│   ├── actions.py                       # DSL, enums, Candidate
│   ├── bridge.py                        # ExecutionBridge, StateGuard
│   ├── observer.py                      # reads economic state
│   ├── evaluator.py                     # §7
│   ├── search/
│   │   ├── random_search.py
│   │   ├── guided_search.py
│   │   └── mutations.py
│   ├── minimizer.py
│   └── report.py
├── scenarios/                           # *.json scenario configs
├── experiments/                         # benchmark drivers (§12)
├── results/
├── foundry.toml
└── README.md
```

**Foundry invariant tests** (`test/invariants/`) are separate from the fuzzer and
assert protocol-level properties on the *patched* contracts, e.g.: under a TWAP
oracle + sane params, no single-tx sequence produces bad debt; AMM `k`
never decreases on a swap; `sum(debt) <= sum(collateralValue)` at the true price.
These document the defenses the fuzzer is meant to defeat on the vulnerable
config.

---

## 11. Build Phases (do them in order)

| Phase | Deliverable | Done-when |
|---|---|---|
| 1 | AMM + LendingMarket + tokens + flash lender, with unit tests for swap math and lending accounting | `forge test` green on unit tests |
| 2 | **One manually written** exploit `.t.sol` proving the vulnerable env is exploitable | manual exploit asserts profit + bad debt |
| 3 | Execution bridge: encode → submit → observe → snapshot-restore, with reliable profit evaluation | replaying the Phase-2 exploit through the Python bridge reproduces identical numbers |
| 4 | Random search that **rediscovers** the exploit | random search finds a qualifying exploit within budget on the vulnerable config |
| 5 | Economic guidance + head-to-head vs random | guided beats random on discovery rate / candidates-to-first-exploit with variance reported |
| 6 | Minimization, generated tests, benchmark report; (stretch) TWAP oracle + multi-block harness | minimized attack + auto `.t.sol` that passes `forge test`; benchmark table produced |

The Phase-2 manual exploit is a **sanity check only** — evaluate automatic
discovery on scenarios whose winning sequence you did **not** feed the engine.

---

## 12. Benchmarking Methodology — **this is what makes it credible**

Most people phone in this section with one seed and no error bars; that invalidates
the headline claim. Do it properly.

- **Primary metric: candidates evaluated before first qualifying exploit**
  (hardware-independent, fair across strategies). Report **mean ± std** over
  **N ≥ 20 seeds**.
- **Secondary:** discovery rate (fraction of runs finding an exploit within the
  fixed budget — *including runs that fail*), wall-clock time to discovery
  (report but don't headline), minimized attack length.
- **Equal budgets:** guided vs random get identical candidate budgets and the
  identical action space and execution path.
- **Parameter sweep:** vary AMM liquidity depth, collateral factor, flash fee,
  and initial capital; report per-configuration.
- **Patched controls:** run both searches against a *patched* scenario (e.g. TWAP
  oracle, or conservative collateral factor) and confirm the exploit rate drops —
  this shows the engine is finding a *real* vulnerability class, not an artifact.
- **Report failures:** runs that find nothing within budget are data, not to be
  discarded.

Deliver a results table (markdown + a CSV in `experiments/`) with, per config and
per strategy: N seeds, discovery rate, mean±std candidates-to-first-exploit,
mean±std wall-clock, mean minimized length.

---

## 13. Extensions (post-MVP, in rough priority order)

1. **TWAP oracle + multi-block harness.** Requires advancing Anvil blocks
   (`evm_mine`, `evm_increaseTime`) between actions and holding attacker capital
   across blocks — a genuinely different execution model than intra-tx snapshot/
   restore. This is the strongest differentiator vs. every "flash-loan exploit
   finder" tutorial, most of which stop at spot oracles.
2. **Second vulnerability class** (e.g. donation/first-depositor inflation, or
   liquidation-incentive mispricing) to show the engine generalizes beyond one
   bug.
3. **Configurable AMM fee** and multi-pool routing.
4. **Coverage-guided hybrid:** combine economic-signal fitness with EVM
   code-coverage (via `--steps-tracing`) for a true greybox signal.
5. Web dashboard for live corpus/fitness visualization.

---

## 14. Non-Goals / Explicit Constraints

- No mainnet forking or real-fund interaction — fully local, deterministic.
- No claim of RL / Bayesian optimization — it is fitness-guided evolutionary
  search; keep the language honest in code and docs.
- No hardcoded winning sequence in the search path; the reference exploit exists
  only as a Phase-2 sanity test.
- Evaluator must never use the contracts' oracle for judging (see §7).
- Gas must come from real metering, never estimates.

---

## Appendix — Data Schemas

**`scenario.json`**

```json
{
  "seed": 1337,
  "amm": { "reserveUsd": "1000000e18", "reserveCol": "1000000e18", "feeBps": 0 },
  "lending": { "usdLiquidity": "500000e18", "collateralFactorBps": 7500 },
  "flash": { "feeBps": 9 },
  "attacker": { "initialCapitalUsd": "10000e18" },
  "evaluator": { "referencePriceUsd": "1e18" },
  "gas": { "gasPriceGwei": 20, "ethPriceUsd": "3000e18" },
  "search": {
    "maxActions": 6,
    "budgetCandidates": 50000,
    "fitnessWeights": {
      "priceDeviation": 1.0, "capacityPerCapital": 1.0,
      "badDebt": 2.0, "profit": 2.0, "novelty": 0.5
    },
    "selectionEpsilon": 0.1
  }
}
```

**`attack.json`** (minimized candidate)

```json
{
  "flashToken": "USD",
  "flashAmount": "250000e18",
  "actions": [
    { "type": "SWAP_USD_FOR_COL", "target": "AMM", "rule": "FRAC_RESERVES", "param": 4000 },
    { "type": "DEPOSIT_COL",       "target": "LENDING", "rule": "PCT_BALANCE", "param": 10000 },
    { "type": "BORROW_USD",        "target": "LENDING", "rule": "PCT_BORROW_CAPACITY", "param": 10000 },
    { "type": "SWAP_COL_FOR_USD",  "target": "AMM", "rule": "PCT_BALANCE", "param": 10000 }
  ],
  "result": {
    "attackerProfitUsd": "…",
    "protocolBadDebtUsd": "…",
    "violatedProperty": "debt_exceeds_collateral_at_reference_price",
    "gasUsed": 0,
    "candidatesToDiscovery": 0,
    "seed": 1337
  }
}
```

**`execution_trace.json`** — array of per-action records:
`{ index, actionType, resolvedAmount, preState, postState }` where each state is
`{ attackerUsd, attackerCol, reserveUsd, reserveCol, oraclePrice, referencePrice, debtUsd, collateralCol }`.
