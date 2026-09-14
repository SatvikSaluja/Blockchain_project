// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MockToken} from "../../contracts/tokens/MockToken.sol";
import {ConstantProductAMM} from "../../contracts/amm/ConstantProductAMM.sol";
import {SpotOracle} from "../../contracts/oracles/SpotOracle.sol";

contract SpotOracleTest is Test {
    MockToken usd;
    MockToken col;
    ConstantProductAMM amm;
    SpotOracle oracle;
    address lp = address(0x1);
    address trader = address(0x2);

    function setUp() public {
        usd = new MockToken("USD", "USD");
        col = new MockToken("Collateral", "COL");
        amm = new ConstantProductAMM(address(usd), address(col));
        oracle = new SpotOracle(address(amm));

        usd.mint(lp, 1_000_000e18);
        col.mint(lp, 1_000_000e18);
        vm.startPrank(lp);
        usd.approve(address(amm), type(uint256).max);
        col.approve(address(amm), type(uint256).max);
        amm.addLiquidity(1_000_000e18, 1_000_000e18);
        vm.stopPrank();
    }

    function test_priceMatchesAmmSpotPrice() public view {
        assertEq(oracle.price(), amm.spotPrice());
        assertEq(oracle.price(), 1e18);
    }

    function test_priceMovesWithReservesWithinSameTx() public {
        usd.mint(trader, 500_000e18);
        vm.startPrank(trader);
        usd.approve(address(amm), type(uint256).max);
        amm.swapUsdForCol(500_000e18);
        vm.stopPrank();

        // The oracle has no independent source — it just re-reads the AMM,
        // so a same-tx swap immediately moves the price it reports.
        assertEq(oracle.price(), amm.spotPrice());
        assertGt(oracle.price(), 1e18);
    }
}
