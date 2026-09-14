// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "../tokens/IERC20.sol";

interface IOracle {
    function price() external view returns (uint256);
}

/// @notice Single-collateral (COL) / single-borrow (USD) market. Trusts
/// whatever `oracle` reports (SPEC §3.4) — with SpotOracle that price is
/// manipulable within a transaction; that's the bug this whole engine hunts.
contract LendingMarket {
    IOracle public immutable oracle;
    IERC20 public immutable usd;
    IERC20 public immutable col;
    uint256 public immutable collateralFactorBps; // e.g. 7500 = 75% max LTV

    mapping(address => uint256) public collateralOf;
    mapping(address => uint256) public debtOf;

    constructor(address _oracle, address _usd, address _col, uint256 _collateralFactorBps) {
        oracle = IOracle(_oracle);
        usd = IERC20(_usd);
        col = IERC20(_col);
        collateralFactorBps = _collateralFactorBps;
    }

    /// @notice Seed USD reserves so the market has liquidity to lend against.
    /// Open like MockToken.mint — setup only, not access-controlled.
    function seedLiquidity(uint256 usdAmount) external {
        require(usd.transferFrom(msg.sender, address(this), usdAmount), "LendingMarket: seed transfer failed");
    }

    function depositCollateral(uint256 colAmount) external {
        require(col.transferFrom(msg.sender, address(this), colAmount), "LendingMarket: col transfer failed");
        collateralOf[msg.sender] += colAmount;
    }

    function withdrawCollateral(uint256 colAmount) external {
        uint256 bal = collateralOf[msg.sender];
        require(bal >= colAmount, "LendingMarket: insufficient collateral");
        uint256 newBal = bal - colAmount;
        require(_maxDebtUsd(newBal) >= debtOf[msg.sender], "LendingMarket: unhealthy");
        collateralOf[msg.sender] = newBal;
        require(col.transfer(msg.sender, colAmount), "LendingMarket: col transfer failed");
    }

    function borrow(uint256 usdAmount) external {
        uint256 newDebt = debtOf[msg.sender] + usdAmount;
        require(newDebt <= _maxDebtUsd(collateralOf[msg.sender]), "LendingMarket: unhealthy");
        debtOf[msg.sender] = newDebt;
        require(usd.transfer(msg.sender, usdAmount), "LendingMarket: usd transfer failed");
    }

    /// @dev Clamps to outstanding debt so an over-eager repay amount (e.g. a
    /// PCT_BALANCE-resolved amount larger than what's owed) doesn't just
    /// revert — mirrors how real markets treat "repay max".
    function repay(uint256 usdAmount) external {
        uint256 debt = debtOf[msg.sender];
        uint256 amount = usdAmount > debt ? debt : usdAmount;
        debtOf[msg.sender] = debt - amount;
        require(usd.transferFrom(msg.sender, address(this), amount), "LendingMarket: usd transfer failed");
    }

    function _maxDebtUsd(uint256 colAmount) internal view returns (uint256) {
        uint256 colValueUsd = (colAmount * oracle.price()) / 1e18;
        return (colValueUsd * collateralFactorBps) / 1e4;
    }
}
