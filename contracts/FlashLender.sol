// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "./tokens/IERC20.sol";

interface IFlashLoanReceiver {
    function onFlashLoan(address token, uint256 amount, uint256 fee, bytes calldata data) external;
}

/// @notice Single-tx flash loan; repayment (principal + fee) is enforced by a
/// balance-delta check after the borrower's callback, not by any trust
/// assumption (SPEC §3.5).
contract FlashLender {
    IERC20 public immutable usd;
    IERC20 public immutable col;
    uint256 public immutable feeBps;

    constructor(address _usd, address _col, uint256 _feeBps) {
        usd = IERC20(_usd);
        col = IERC20(_col);
        feeBps = _feeBps;
    }

    function flashLoan(address token, uint256 amount, bytes calldata data) external {
        require(token == address(usd) || token == address(col), "FlashLender: unsupported token");
        IERC20 t = IERC20(token);

        uint256 preBalance = t.balanceOf(address(this));
        require(preBalance >= amount, "FlashLender: insufficient liquidity");
        uint256 fee = (amount * feeBps) / 1e4;

        require(t.transfer(msg.sender, amount), "FlashLender: transfer failed");
        IFlashLoanReceiver(msg.sender).onFlashLoan(token, amount, fee, data);

        require(t.balanceOf(address(this)) >= preBalance + fee, "FlashLender: not repaid");
    }
}
