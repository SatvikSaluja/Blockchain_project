// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MockToken} from "../../contracts/tokens/MockToken.sol";
import {ConstantProductAMM} from "../../contracts/amm/ConstantProductAMM.sol";

contract AMMTest is Test {
    MockToken usd;
    MockToken col;
    ConstantProductAMM amm;
    address lp = address(0x1);
    address trader = address(0x2);

    function setUp() public {
        usd = new MockToken("USD", "USD");
        col = new MockToken("Collateral", "COL");
        amm = new ConstantProductAMM(address(usd), address(col), 0);

        usd.mint(lp, 1_000_000e18);
        col.mint(lp, 1_000_000e18);
        vm.startPrank(lp);
        usd.approve(address(amm), type(uint256).max);
        col.approve(address(amm), type(uint256).max);
        amm.addLiquidity(1_000_000e18, 1_000_000e18);
        vm.stopPrank();
    }

    function test_spotPriceIsOneAtEqualReserves() public view {
        assertEq(amm.spotPrice(), 1e18);
    }

    function test_swapUsdForCol_matchesConstantProductFormula() public {
        usd.mint(trader, 10_000e18);
        vm.startPrank(trader);
        usd.approve(address(amm), type(uint256).max);

        (uint256 rUsdBefore, uint256 rColBefore) = amm.getReserves();
        uint256 expectedOut = (rColBefore * 10_000e18) / (rUsdBefore + 10_000e18);

        uint256 out = amm.swapUsdForCol(10_000e18);
        vm.stopPrank();

        assertEq(out, expectedOut);
        assertEq(col.balanceOf(trader), expectedOut);
    }

    function test_swapColForUsd_matchesConstantProductFormula() public {
        col.mint(trader, 10_000e18);
        vm.startPrank(trader);
        col.approve(address(amm), type(uint256).max);

        (uint256 rUsdBefore, uint256 rColBefore) = amm.getReserves();
        uint256 expectedOut = (rUsdBefore * 10_000e18) / (rColBefore + 10_000e18);

        uint256 out = amm.swapColForUsd(10_000e18);
        vm.stopPrank();

        assertEq(out, expectedOut);
        assertEq(usd.balanceOf(trader), expectedOut);
    }

    function test_kNeverDecreasesAcrossSwaps() public {
        (uint256 rUsd0, uint256 rCol0) = amm.getReserves();
        uint256 k0 = rUsd0 * rCol0;

        usd.mint(trader, 50_000e18);
        vm.startPrank(trader);
        usd.approve(address(amm), type(uint256).max);
        amm.swapUsdForCol(50_000e18);
        vm.stopPrank();

        (uint256 rUsd1, uint256 rCol1) = amm.getReserves();
        assertGe(rUsd1 * rCol1, k0);

        vm.startPrank(trader);
        col.approve(address(amm), type(uint256).max);
        amm.swapColForUsd(col.balanceOf(trader));
        vm.stopPrank();

        (uint256 rUsd2, uint256 rCol2) = amm.getReserves();
        assertGe(rUsd2 * rCol2, rUsd1 * rCol1);
    }

    function test_largeSwapMovesPriceAwayFromOne() public {
        usd.mint(trader, 500_000e18);
        vm.startPrank(trader);
        usd.approve(address(amm), type(uint256).max);
        amm.swapUsdForCol(500_000e18);
        vm.stopPrank();

        // Buying COL with USD pushes reserveUsd up and reserveCol down, so
        // spot price (USD per COL) rises above 1e18.
        assertGt(amm.spotPrice(), 1e18);
    }

    function test_swapZeroInReverts() public {
        vm.expectRevert("AMM: zero in");
        amm.swapUsdForCol(0);
    }

    function test_nonzeroFee_reducesOutputVsZeroFee() public {
        ConstantProductAMM feeAmm = new ConstantProductAMM(address(usd), address(col), 30); // 0.30%
        usd.mint(lp, 1_000_000e18);
        col.mint(lp, 1_000_000e18);
        vm.startPrank(lp);
        usd.approve(address(feeAmm), type(uint256).max);
        col.approve(address(feeAmm), type(uint256).max);
        feeAmm.addLiquidity(1_000_000e18, 1_000_000e18);
        vm.stopPrank();

        usd.mint(trader, 10_000e18);
        vm.startPrank(trader);
        usd.approve(address(feeAmm), type(uint256).max);

        (uint256 rUsd, uint256 rCol) = feeAmm.getReserves();
        uint256 inWithFee = (10_000e18 * (1e4 - 30)) / 1e4;
        uint256 expectedOut = (rCol * inWithFee) / (rUsd + inWithFee);
        uint256 zeroFeeOut = (rCol * 10_000e18) / (rUsd + 10_000e18);

        uint256 out = feeAmm.swapUsdForCol(10_000e18);
        vm.stopPrank();

        assertEq(out, expectedOut);
        assertLt(out, zeroFeeOut, "fee should strictly reduce output vs the zero-fee formula");
    }

    function test_nonzeroFee_strictlyIncreasesK() public {
        ConstantProductAMM feeAmm = new ConstantProductAMM(address(usd), address(col), 30);
        usd.mint(lp, 1_000_000e18);
        col.mint(lp, 1_000_000e18);
        vm.startPrank(lp);
        usd.approve(address(feeAmm), type(uint256).max);
        col.approve(address(feeAmm), type(uint256).max);
        feeAmm.addLiquidity(1_000_000e18, 1_000_000e18);
        vm.stopPrank();

        (uint256 rUsd0, uint256 rCol0) = feeAmm.getReserves();
        uint256 k0 = rUsd0 * rCol0;

        usd.mint(trader, 10_000e18);
        vm.startPrank(trader);
        usd.approve(address(feeAmm), type(uint256).max);
        feeAmm.swapUsdForCol(10_000e18);
        vm.stopPrank();

        (uint256 rUsd1, uint256 rCol1) = feeAmm.getReserves();
        // Unlike the zero-fee case (k merely non-decreasing from rounding),
        // a real fee must strictly grow k — that's the fee accruing to LPs.
        assertGt(rUsd1 * rCol1, k0);
    }
}
