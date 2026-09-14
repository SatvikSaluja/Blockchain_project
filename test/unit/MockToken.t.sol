// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MockToken} from "../../contracts/tokens/MockToken.sol";

contract MockTokenTest is Test {
    MockToken token;
    address alice = address(0xA11CE);
    address bob = address(0xB0B);

    function setUp() public {
        token = new MockToken("USD Coin", "USD");
    }

    function test_mintIncreasesBalanceAndSupply() public {
        token.mint(alice, 100e18);
        assertEq(token.balanceOf(alice), 100e18);
        assertEq(token.totalSupply(), 100e18);
    }

    function test_transferMovesBalance() public {
        token.mint(alice, 100e18);
        vm.prank(alice);
        token.transfer(bob, 40e18);
        assertEq(token.balanceOf(alice), 60e18);
        assertEq(token.balanceOf(bob), 40e18);
    }

    function test_transferRevertsOnInsufficientBalance() public {
        vm.prank(alice);
        vm.expectRevert("MockToken: insufficient balance");
        token.transfer(bob, 1e18);
    }

    function test_approveAndTransferFrom() public {
        token.mint(alice, 100e18);
        vm.prank(alice);
        token.approve(bob, 30e18);

        vm.prank(bob);
        token.transferFrom(alice, bob, 30e18);

        assertEq(token.balanceOf(alice), 70e18);
        assertEq(token.balanceOf(bob), 30e18);
        assertEq(token.allowance(alice, bob), 0);
    }

    function test_transferFromRevertsWithoutAllowance() public {
        token.mint(alice, 100e18);
        vm.prank(bob);
        vm.expectRevert("MockToken: insufficient allowance");
        token.transferFrom(alice, bob, 1e18);
    }

    function test_infiniteAllowanceNotDecremented() public {
        token.mint(alice, 100e18);
        vm.prank(alice);
        token.approve(bob, type(uint256).max);

        vm.prank(bob);
        token.transferFrom(alice, bob, 10e18);

        assertEq(token.allowance(alice, bob), type(uint256).max);
    }
}
