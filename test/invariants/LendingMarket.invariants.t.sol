// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {StdInvariant} from "forge-std/StdInvariant.sol";
import {MockToken} from "../../contracts/tokens/MockToken.sol";
import {ConstantProductAMM} from "../../contracts/amm/ConstantProductAMM.sol";
import {SpotOracle} from "../../contracts/oracles/SpotOracle.sol";
import {LendingMarket} from "../../contracts/lending/LendingMarket.sol";

/// @notice Handler: one well-capitalized actor doing ordinary, one-call-at-
/// a-time market usage (swap, deposit, borrow, repay, withdraw) — NOT a
/// flash-loaned, single-tx AttackExecutor sequence. Trading spends only
/// from a fixed starting budget, never from borrowed funds, so this models
/// "a whale's finite real capital moving price," not a multi-block
/// bootstrapped leverage loop (that threat model needs a TWAP oracle to
/// defend against — SPEC §13.1 / Task 32, not built).
contract LendingHandler is Test {
    MockToken usd;
    MockToken col;
    ConstantProductAMM amm;
    LendingMarket lending;

    uint256 public tradingUsdRemaining;
    uint256 public tradingColRemaining;

    constructor(
        MockToken _usd,
        MockToken _col,
        ConstantProductAMM _amm,
        LendingMarket _lending,
        uint256 usdBudget,
        uint256 colBudget
    ) {
        usd = _usd;
        col = _col;
        amm = _amm;
        lending = _lending;
        tradingUsdRemaining = usdBudget;
        tradingColRemaining = colBudget;
        usd.mint(address(this), usdBudget);
        col.mint(address(this), colBudget);
        usd.approve(address(amm), type(uint256).max);
        col.approve(address(amm), type(uint256).max);
        usd.approve(address(lending), type(uint256).max);
        col.approve(address(lending), type(uint256).max);
    }

    function swapUsdForCol(uint256 usdIn) external {
        usdIn = bound(usdIn, 0, tradingUsdRemaining);
        if (usdIn == 0) return;
        tradingUsdRemaining -= usdIn;
        amm.swapUsdForCol(usdIn);
    }

    function swapColForUsd(uint256 colIn) external {
        colIn = bound(colIn, 0, tradingColRemaining);
        if (colIn == 0) return;
        tradingColRemaining -= colIn;
        amm.swapColForUsd(colIn);
    }

    function depositCollateral(uint256 amount) external {
        amount = bound(amount, 0, col.balanceOf(address(this)));
        if (amount == 0) return;
        lending.depositCollateral(amount);
    }

    function borrow(uint256 amount) external {
        amount = bound(amount, 0, 200_000e18);
        if (amount == 0) return;
        lending.borrow(amount);
    }

    function repay(uint256 amount) external {
        amount = bound(amount, 0, usd.balanceOf(address(this)));
        if (amount == 0) return;
        lending.repay(amount);
    }

    function withdrawCollateral(uint256 amount) external {
        amount = bound(amount, 0, lending.collateralOf(address(this)));
        if (amount == 0) return;
        lending.withdrawCollateral(amount);
    }
}

/// @notice SPEC §10's invariants bullet: "sum(debt) <= sum(collateralValue)
/// at the true price" under "sane params." Here "sane params" is the same
/// conservative collateral factor experiments/benchmark.py's
/// patched_low_collateral_factor control uses (30% vs the vulnerable
/// scenario's 75%). "True price" is REFERENCE_PRICE_USD — the same fixed,
/// independent judge price SPEC §7 requires the Python evaluator to use
/// instead of the contracts' own (manipulable) oracle.
///
/// Distinct from the Python engine: that searches for a single flash-
/// loaned transaction that breaks solvency. This drives many ordinary,
/// sequential, non-flash-loaned transactions from one finitely-capitalized
/// actor and checks solvency after every one — "bounded organic activity
/// alone can't manufacture bad debt under a conservative factor."
contract LendingMarketInvariantsTest is StdInvariant, Test {
    uint256 constant SEED_USD = 1_000_000e18;
    uint256 constant SEED_COL = 1_000_000e18;
    uint256 constant LENDING_USD_LIQUIDITY = 500_000e18;
    uint256 constant CONSERVATIVE_COLLATERAL_FACTOR_BPS = 3000; // matches benchmark.py's patched control
    uint256 constant REFERENCE_PRICE_USD = 1e18;

    // Comparable order of magnitude to the reference exploit's flash amount
    // (~287k, see results/run_001/report.md) — but real capital, not borrowed.
    uint256 constant WHALE_USD_BUDGET = 250_000e18;
    uint256 constant WHALE_COL_BUDGET = 250_000e18;

    LendingMarket lending;
    LendingHandler handler;

    function setUp() public {
        MockToken usd = new MockToken("USD", "USD");
        MockToken col = new MockToken("Collateral", "COL");
        ConstantProductAMM amm = new ConstantProductAMM(address(usd), address(col));
        SpotOracle oracle = new SpotOracle(address(amm));
        lending = new LendingMarket(address(oracle), address(usd), address(col), CONSERVATIVE_COLLATERAL_FACTOR_BPS);

        usd.mint(address(this), SEED_USD);
        col.mint(address(this), SEED_COL);
        usd.approve(address(amm), SEED_USD);
        col.approve(address(amm), SEED_COL);
        amm.addLiquidity(SEED_USD, SEED_COL);

        usd.mint(address(this), LENDING_USD_LIQUIDITY);
        usd.approve(address(lending), LENDING_USD_LIQUIDITY);
        lending.seedLiquidity(LENDING_USD_LIQUIDITY);

        handler = new LendingHandler(usd, col, amm, lending, WHALE_USD_BUDGET, WHALE_COL_BUDGET);
        targetContract(address(handler));
    }

    function invariant_noBadDebtAtReferencePriceUnderConservativeFactor() public view {
        uint256 debtUsd = lending.debtOf(address(handler));
        uint256 colValueAtReferencePrice = (lending.collateralOf(address(handler)) * REFERENCE_PRICE_USD) / 1e18;
        assertLe(debtUsd, colValueAtReferencePrice);
    }
}
