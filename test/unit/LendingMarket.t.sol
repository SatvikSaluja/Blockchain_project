// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MockToken} from "../../contracts/tokens/MockToken.sol";
import {LendingMarket} from "../../contracts/lending/LendingMarket.sol";

/// @dev Fixed-price oracle so lending accounting tests are independent of
/// the AMM — isolates the unit under test per SPEC §3.4's formulas.
contract MockOracle {
    uint256 public price_ = 1e18;

    function price() external view returns (uint256) {
        return price_;
    }

    function setPrice(uint256 p) external {
        price_ = p;
    }
}

contract LendingMarketTest is Test {
    MockToken usd;
    MockToken col;
    MockOracle oracle;
    LendingMarket market;
    address lender = address(0x1);
    address user = address(0x2);
    uint256 constant CF_BPS = 7500; // 75% max LTV

    function setUp() public {
        usd = new MockToken("USD", "USD");
        col = new MockToken("Collateral", "COL");
        oracle = new MockOracle();
        market = new LendingMarket(address(oracle), address(usd), address(col), CF_BPS);

        usd.mint(lender, 1_000_000e18);
        vm.startPrank(lender);
        usd.approve(address(market), type(uint256).max);
        market.seedLiquidity(1_000_000e18);
        vm.stopPrank();

        col.mint(user, 10_000e18);
        vm.startPrank(user);
        col.approve(address(market), type(uint256).max);
        usd.approve(address(market), type(uint256).max);
        vm.stopPrank();
    }

    function test_depositCollateralTracksBalance() public {
        vm.prank(user);
        market.depositCollateral(1_000e18);
        assertEq(market.collateralOf(user), 1_000e18);
        assertEq(col.balanceOf(address(market)), 1_000e18);
    }

    function test_borrowUpToMaxLtvSucceeds() public {
        vm.startPrank(user);
        market.depositCollateral(1_000e18); // price=1e18 -> colValue=1000e18
        market.borrow(750e18); // exactly 75% of 1000e18
        vm.stopPrank();

        assertEq(market.debtOf(user), 750e18);
        assertEq(usd.balanceOf(user), 750e18);
    }

    function test_borrowAboveMaxLtvReverts() public {
        vm.startPrank(user);
        market.depositCollateral(1_000e18);
        vm.expectRevert("LendingMarket: unhealthy");
        market.borrow(750e18 + 1);
        vm.stopPrank();
    }

    function test_repayReducesDebt() public {
        vm.startPrank(user);
        market.depositCollateral(1_000e18);
        market.borrow(500e18);
        market.repay(200e18);
        vm.stopPrank();

        assertEq(market.debtOf(user), 300e18);
    }

    function test_repayClampsToOutstandingDebt() public {
        usd.mint(user, 1_000e18); // give user spare USD beyond their debt
        vm.startPrank(user);
        market.depositCollateral(1_000e18);
        market.borrow(500e18);
        market.repay(10_000e18); // way more than owed
        vm.stopPrank();

        assertEq(market.debtOf(user), 0);
    }

    function test_withdrawCollateralWithNoDebtSucceeds() public {
        vm.startPrank(user);
        market.depositCollateral(1_000e18);
        market.withdrawCollateral(1_000e18);
        vm.stopPrank();

        assertEq(market.collateralOf(user), 0);
        assertEq(col.balanceOf(user), 10_000e18);
    }

    function test_withdrawCollateralRevertsIfWouldBreachHealth() public {
        vm.startPrank(user);
        market.depositCollateral(1_000e18);
        market.borrow(750e18); // maxed out at 75% LTV
        vm.expectRevert("LendingMarket: unhealthy");
        market.withdrawCollateral(1);
        vm.stopPrank();
    }

    function test_priceIncreaseRaisesBorrowCapacity() public {
        vm.prank(user);
        market.depositCollateral(1_000e18);

        oracle.setPrice(2e18); // COL doubles in USD terms
        vm.prank(user);
        market.borrow(1_500e18); // 75% of the now-doubled 2000e18 value
        assertEq(market.debtOf(user), 1_500e18);
    }
}
