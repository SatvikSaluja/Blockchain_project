// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MockToken} from "../../contracts/tokens/MockToken.sol";
import {ConstantProductAMM} from "../../contracts/amm/ConstantProductAMM.sol";
import {SpotOracle} from "../../contracts/oracles/SpotOracle.sol";
import {LendingMarket} from "../../contracts/lending/LendingMarket.sol";
import {FlashLender} from "../../contracts/FlashLender.sol";
import {AttackExecutor} from "../../contracts/AttackExecutor.sol";

/// @notice Exercises each ActionType/AmountRule combination in the DSL
/// interpreter (SPEC §3.6). AttackExecutor is pre-funded directly (beyond
/// what the flash loan supplies) so each test can isolate one action's
/// resolution/execution logic without needing a full profitable round trip
/// — that end-to-end economic property is Phase 2's job, not this unit test.
contract AttackExecutorTest is Test {
    MockToken usd;
    MockToken col;
    ConstantProductAMM amm;
    SpotOracle oracle;
    LendingMarket lending;
    FlashLender flashLender;
    AttackExecutor executor;

    uint256 constant CF_BPS = 7500;
    uint256 constant FLASH_FEE_BPS = 9;
    uint256 constant PREFUND = 500_000e18;

    function setUp() public {
        usd = new MockToken("USD", "USD");
        col = new MockToken("Collateral", "COL");
        amm = new ConstantProductAMM(address(usd), address(col));
        oracle = new SpotOracle(address(amm));
        lending = new LendingMarket(address(oracle), address(usd), address(col), CF_BPS);
        flashLender = new FlashLender(address(usd), address(col), FLASH_FEE_BPS);

        address lp = address(0x1);
        usd.mint(lp, 1_000_000e18);
        col.mint(lp, 1_000_000e18);
        vm.startPrank(lp);
        usd.approve(address(amm), type(uint256).max);
        col.approve(address(amm), type(uint256).max);
        amm.addLiquidity(1_000_000e18, 1_000_000e18);
        vm.stopPrank();

        usd.mint(address(this), 500_000e18);
        usd.approve(address(lending), type(uint256).max);
        lending.seedLiquidity(500_000e18);

        usd.mint(address(flashLender), 1_000_000e18);
        col.mint(address(flashLender), 1_000_000e18);

        executor = new AttackExecutor(
            address(amm), address(oracle), address(lending), address(flashLender), address(usd), address(col)
        );

        // Seed capital already sitting in the executor, independent of the
        // flash loan, so single actions can be tested without a round trip.
        usd.mint(address(executor), PREFUND);
        col.mint(address(executor), PREFUND);
    }

    function _action(AttackExecutor.ActionType t, address target, AttackExecutor.AmountRule r, uint256 param)
        internal
        pure
        returns (AttackExecutor.Action memory)
    {
        return AttackExecutor.Action({
            actionType: uint8(t),
            target: target,
            amountRule: uint8(r),
            amountParam: param
        });
    }

    function test_swapUsdForCol_fixedRule() public {
        (uint256 rUsd, uint256 rCol) = amm.getReserves();
        uint256 expectedOut = (rCol * 10_000e18) / (rUsd + 10_000e18);
        uint256 flashAmount = 100_000e18;
        uint256 fee = (flashAmount * FLASH_FEE_BPS) / 1e4;

        AttackExecutor.Action[] memory actions = new AttackExecutor.Action[](1);
        actions[0] = _action(AttackExecutor.ActionType.SWAP_USD_FOR_COL, address(amm), AttackExecutor.AmountRule.FIXED, 10_000e18);
        executor.executeAttack(address(usd), flashAmount, actions);

        assertEq(usd.balanceOf(address(executor)), PREFUND - 10_000e18 - fee);
        assertEq(col.balanceOf(address(executor)), PREFUND + expectedOut);
    }

    function test_swapColForUsd_pctBalanceRule() public {
        uint256 flashAmount = 50_000e18;
        uint256 colBalAtSwap = PREFUND + flashAmount;
        uint256 resolvedIn = (colBalAtSwap * 1000) / 1e4; // 10% of balance
        (uint256 rUsd, uint256 rCol) = amm.getReserves();
        uint256 expectedOut = (rUsd * resolvedIn) / (rCol + resolvedIn);
        uint256 fee = (flashAmount * FLASH_FEE_BPS) / 1e4;

        AttackExecutor.Action[] memory actions = new AttackExecutor.Action[](1);
        actions[0] = _action(AttackExecutor.ActionType.SWAP_COL_FOR_USD, address(amm), AttackExecutor.AmountRule.PCT_BALANCE, 1000);
        executor.executeAttack(address(col), flashAmount, actions);

        // Flash principal passes through (received, then repaid) — only the
        // fee and the swapped-away amount net out of the executor's balance.
        assertEq(col.balanceOf(address(executor)), PREFUND - resolvedIn - fee);
        assertEq(usd.balanceOf(address(executor)), PREFUND + expectedOut);
    }

    function test_depositCol_fracReservesRule() public {
        (, uint256 rCol) = amm.getReserves();
        uint256 resolved = (rCol * 1000) / 1e4; // 10% of AMM's col reserve
        uint256 flashAmount = 10_000e18;
        uint256 fee = (flashAmount * FLASH_FEE_BPS) / 1e4;

        AttackExecutor.Action[] memory actions = new AttackExecutor.Action[](1);
        actions[0] = _action(AttackExecutor.ActionType.DEPOSIT_COL, address(lending), AttackExecutor.AmountRule.FRAC_RESERVES, 1000);
        executor.executeAttack(address(col), flashAmount, actions);

        assertEq(lending.collateralOf(address(executor)), resolved);
        // Flash principal passes through — only the fee and the deposited
        // amount net out of the executor's own COL balance.
        assertEq(col.balanceOf(address(executor)), PREFUND - resolved - fee);
    }

    function test_borrowUsd_pctBorrowCapacityRule() public {
        uint256 depositAmt = 100_000e18;
        uint256 flashAmount = 10_000e18;

        AttackExecutor.Action[] memory actions = new AttackExecutor.Action[](2);
        actions[0] = _action(AttackExecutor.ActionType.DEPOSIT_COL, address(lending), AttackExecutor.AmountRule.FIXED, depositAmt);
        actions[1] = _action(AttackExecutor.ActionType.BORROW_USD, address(lending), AttackExecutor.AmountRule.PCT_BORROW_CAPACITY, 10_000);
        executor.executeAttack(address(usd), flashAmount, actions);

        uint256 expectedMaxDebt = (depositAmt * oracle.price() / 1e18) * CF_BPS / 1e4;
        assertEq(lending.debtOf(address(executor)), expectedMaxDebt);
    }

    function test_repayUsd_fixedRule() public {
        uint256 depositAmt = 100_000e18;
        uint256 borrowAmt = 50_000e18;
        uint256 repayAmt = 20_000e18;
        uint256 flashAmount = 10_000e18;

        AttackExecutor.Action[] memory actions = new AttackExecutor.Action[](3);
        actions[0] = _action(AttackExecutor.ActionType.DEPOSIT_COL, address(lending), AttackExecutor.AmountRule.FIXED, depositAmt);
        actions[1] = _action(AttackExecutor.ActionType.BORROW_USD, address(lending), AttackExecutor.AmountRule.FIXED, borrowAmt);
        actions[2] = _action(AttackExecutor.ActionType.REPAY_USD, address(lending), AttackExecutor.AmountRule.FIXED, repayAmt);
        executor.executeAttack(address(usd), flashAmount, actions);

        assertEq(lending.debtOf(address(executor)), borrowAmt - repayAmt);
    }

    function test_withdrawCol_fixedRule() public {
        uint256 depositAmt = 100_000e18;
        uint256 withdrawAmt = 40_000e18;
        uint256 flashAmount = 1_000e18;

        AttackExecutor.Action[] memory actions = new AttackExecutor.Action[](2);
        actions[0] = _action(AttackExecutor.ActionType.DEPOSIT_COL, address(lending), AttackExecutor.AmountRule.FIXED, depositAmt);
        actions[1] = _action(AttackExecutor.ActionType.WITHDRAW_COL, address(lending), AttackExecutor.AmountRule.FIXED, withdrawAmt);
        executor.executeAttack(address(col), flashAmount, actions);

        assertEq(lending.collateralOf(address(executor)), depositAmt - withdrawAmt);
    }

    function test_revertsOnTooManyActions() public {
        AttackExecutor.Action[] memory actions = new AttackExecutor.Action[](7);
        for (uint256 i = 0; i < 7; i++) {
            actions[i] = _action(AttackExecutor.ActionType.DEPOSIT_COL, address(lending), AttackExecutor.AmountRule.FIXED, 1);
        }
        vm.expectRevert("AttackExecutor: too many actions");
        executor.executeAttack(address(usd), 1_000e18, actions);
    }

    function test_revertsOnBadTarget() public {
        AttackExecutor.Action[] memory actions = new AttackExecutor.Action[](1);
        actions[0] = _action(AttackExecutor.ActionType.DEPOSIT_COL, address(0xBEEF), AttackExecutor.AmountRule.FIXED, 1);
        vm.expectRevert("AttackExecutor: bad target");
        executor.executeAttack(address(usd), 1_000e18, actions);
    }

    function test_revertsWhenCalledByNonOwner() public {
        AttackExecutor.Action[] memory actions = new AttackExecutor.Action[](0);
        vm.prank(address(0xBADD));
        vm.expectRevert("AttackExecutor: not owner");
        executor.executeAttack(address(usd), 1_000e18, actions);
    }
}
