// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MockToken} from "../../contracts/tokens/MockToken.sol";
import {FlashLender, IFlashLoanReceiver} from "../../contracts/FlashLender.sol";

/// @dev Test borrower that can be toggled to repay correctly, underpay, or
/// not repay at all.
contract TestBorrower is IFlashLoanReceiver {
    MockToken public immutable usd;
    FlashLender public immutable lender;
    bool public shouldRepay = true;
    uint256 public shortfall;

    constructor(address _usd, address _lender) {
        usd = MockToken(_usd);
        lender = FlashLender(_lender);
    }

    function setShouldRepay(bool v) external {
        shouldRepay = v;
    }

    function setShortfall(uint256 s) external {
        shortfall = s;
    }

    function borrow(uint256 amount, bytes calldata data) external {
        lender.flashLoan(address(usd), amount, data);
    }

    function onFlashLoan(address, uint256 amount, uint256 fee, bytes calldata) external {
        if (shouldRepay) {
            usd.transfer(address(lender), amount + fee - shortfall);
        }
    }
}

contract FlashLenderTest is Test {
    MockToken usd;
    MockToken col;
    FlashLender lender;
    TestBorrower borrower;
    uint256 constant FEE_BPS = 9; // 0.09%

    function setUp() public {
        usd = new MockToken("USD", "USD");
        col = new MockToken("Collateral", "COL");
        lender = new FlashLender(address(usd), address(col), FEE_BPS);
        usd.mint(address(lender), 1_000_000e18);

        borrower = new TestBorrower(address(usd), address(lender));
        // fund borrower with enough to cover the fee on top of the loan
        usd.mint(address(borrower), 1_000e18);
    }

    function test_flashLoanRepaidWithFeeSucceeds() public {
        uint256 preLender = usd.balanceOf(address(lender));
        borrower.borrow(100_000e18, "");
        uint256 expectedFee = (100_000e18 * FEE_BPS) / 1e4;
        assertEq(usd.balanceOf(address(lender)), preLender + expectedFee);
    }

    function test_flashLoanRevertsIfUnderpaid() public {
        borrower.setShortfall(1);
        vm.expectRevert("FlashLender: not repaid");
        borrower.borrow(100_000e18, "");
    }

    function test_flashLoanRevertsIfNotRepaid() public {
        borrower.setShouldRepay(false);
        vm.expectRevert("FlashLender: not repaid");
        borrower.borrow(100_000e18, "");
    }

    function test_flashLoanRevertsOnUnsupportedToken() public {
        MockToken other = new MockToken("Other", "OTH");
        vm.expectRevert("FlashLender: unsupported token");
        lender.flashLoan(address(other), 1, "");
    }

    function test_flashLoanRevertsOnInsufficientLiquidity() public {
        vm.expectRevert("FlashLender: insufficient liquidity");
        borrower.borrow(10_000_000e18, "");
    }
}
