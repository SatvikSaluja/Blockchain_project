// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "../tokens/IERC20.sol";

/// @notice Uniswap-v2-style x*y=k pool. Zero swap fee in v1 (SPEC §3.2) — a
/// configurable fee is a post-MVP extension; the zero-fee pool keeps the
/// manipulation math exact for the hand-derived Phase-2 exploit.
contract ConstantProductAMM {
    IERC20 public immutable usd;
    IERC20 public immutable col;

    uint256 public reserveUsd;
    uint256 public reserveCol;

    constructor(address _usd, address _col) {
        usd = IERC20(_usd);
        col = IERC20(_col);
    }

    function addLiquidity(uint256 usdAmount, uint256 colAmount) external {
        require(usd.transferFrom(msg.sender, address(this), usdAmount), "AMM: usd transfer failed");
        require(col.transferFrom(msg.sender, address(this), colAmount), "AMM: col transfer failed");
        reserveUsd += usdAmount;
        reserveCol += colAmount;
    }

    function getReserves() external view returns (uint256 rUsd, uint256 rCol) {
        return (reserveUsd, reserveCol);
    }

    /// @dev Exact-in swap. `out = (rOut * in) / (rIn + in)` — the zero-fee
    /// constant-product form. Reverts on zero-out or a k decrease.
    function swapUsdForCol(uint256 usdIn) external returns (uint256 colOut) {
        require(usdIn > 0, "AMM: zero in");
        uint256 rUsd = reserveUsd;
        uint256 rCol = reserveCol;
        colOut = (rCol * usdIn) / (rUsd + usdIn);
        require(colOut > 0, "AMM: zero out");

        require(usd.transferFrom(msg.sender, address(this), usdIn), "AMM: usd transfer failed");
        uint256 newUsd = rUsd + usdIn;
        uint256 newCol = rCol - colOut;
        require(newUsd * newCol >= rUsd * rCol, "AMM: k violated");
        reserveUsd = newUsd;
        reserveCol = newCol;
        require(col.transfer(msg.sender, colOut), "AMM: col transfer failed");
    }

    function swapColForUsd(uint256 colIn) external returns (uint256 usdOut) {
        require(colIn > 0, "AMM: zero in");
        uint256 rUsd = reserveUsd;
        uint256 rCol = reserveCol;
        usdOut = (rUsd * colIn) / (rCol + colIn);
        require(usdOut > 0, "AMM: zero out");

        require(col.transferFrom(msg.sender, address(this), colIn), "AMM: col transfer failed");
        uint256 newCol = rCol + colIn;
        uint256 newUsd = rUsd - usdOut;
        require(newUsd * newCol >= rUsd * rCol, "AMM: k violated");
        reserveUsd = newUsd;
        reserveCol = newCol;
        require(usd.transfer(msg.sender, usdOut), "AMM: usd transfer failed");
    }

    /// @notice USD per 1 COL, 1e18-scaled. This is the manipulable price the
    /// vulnerable SpotOracle trusts directly (SPEC §3.3).
    function spotPrice() external view returns (uint256) {
        require(reserveCol > 0, "AMM: no col reserve");
        return (reserveUsd * 1e18) / reserveCol;
    }
}
