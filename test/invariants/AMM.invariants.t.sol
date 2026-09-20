// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {StdInvariant} from "forge-std/StdInvariant.sol";
import {MockToken} from "../../contracts/tokens/MockToken.sol";
import {ConstantProductAMM} from "../../contracts/amm/ConstantProductAMM.sol";

/// @notice Handler: bounded random swaps against a fresh, self-funded AMM.
/// Mints itself whatever it needs so calls are plausible swaps rather than
/// guaranteed-revert insufficient-balance noops.
contract AMMHandler is Test {
    MockToken usd;
    MockToken col;
    ConstantProductAMM amm;

    constructor(MockToken _usd, MockToken _col, ConstantProductAMM _amm) {
        usd = _usd;
        col = _col;
        amm = _amm;
    }

    function swapUsdForCol(uint256 usdIn) external {
        usdIn = bound(usdIn, 1, 500_000e18);
        usd.mint(address(this), usdIn);
        usd.approve(address(amm), usdIn);
        amm.swapUsdForCol(usdIn);
    }

    function swapColForUsd(uint256 colIn) external {
        colIn = bound(colIn, 1, 500_000e18);
        col.mint(address(this), colIn);
        col.approve(address(amm), colIn);
        amm.swapColForUsd(colIn);
    }
}

/// @notice SPEC §10's invariants bullet: "AMM k never decreases on a swap."
/// AMM.t.sol already checks this with a scripted sequence of calls; this is
/// the genuine article — forge's stateful fuzzer drives a random sequence
/// of handler calls and re-checks the invariant after every one.
contract AMMInvariantsTest is StdInvariant, Test {
    uint256 constant SEED_USD = 1_000_000e18;
    uint256 constant SEED_COL = 1_000_000e18;

    ConstantProductAMM amm;
    uint256 k0;

    function setUp() public {
        MockToken usd = new MockToken("USD", "USD");
        MockToken col = new MockToken("Collateral", "COL");
        amm = new ConstantProductAMM(address(usd), address(col), 0);

        usd.mint(address(this), SEED_USD);
        col.mint(address(this), SEED_COL);
        usd.approve(address(amm), SEED_USD);
        col.approve(address(amm), SEED_COL);
        amm.addLiquidity(SEED_USD, SEED_COL);
        k0 = SEED_USD * SEED_COL;

        AMMHandler handler = new AMMHandler(usd, col, amm);
        targetContract(address(handler));
    }

    function invariant_kNeverDecreases() public view {
        (uint256 rUsd, uint256 rCol) = amm.getReserves();
        assertGe(rUsd * rCol, k0);
    }
}
